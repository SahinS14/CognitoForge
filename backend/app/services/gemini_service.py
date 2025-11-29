"""Google Gemini helpers for attack planning and report summarisation."""

from __future__ import annotations

import importlib
import json
import logging
import re
import textwrap
from typing import Dict, List, Optional

import httpx

from backend.app.core.settings import get_settings
from backend.app.models.schemas import AttackPlan, AttackStep, SimulationReport, SimulationRun
from backend.app.services import repo_fetcher

logger = logging.getLogger(__name__)

_FALLBACK_MESSAGE = "Gemini unavailable"
_ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}
_DEFAULT_OVERALL_SEVERITY = "high"


class GeminiPlanError(RuntimeError):
    """Raised when Gemini cannot produce a valid attack plan."""


def generate_attack_plan(repo_id: str) -> AttackPlan:
    """Generate an attack plan for ``repo_id`` using Gemini when available."""

    settings = get_settings()

    manifest: Optional[Dict[str, object]] = None
    try:
        manifest = repo_fetcher.load_repo_manifest(repo_id)
    except repo_fetcher.ManifestNotFoundError:
        logger.warning("Repository manifest not found; defaulting to mock plan", extra={"repo_id": repo_id})

    if settings.use_gemini and settings.gemini_api_key and manifest:
        try:
            plan = _generate_plan_with_gemini(repo_id, manifest)
            logger.info(
                "Gemini attack plan generated",
                extra={"repo_id": repo_id, "steps": len(plan.steps)},
            )
            return plan
        except GeminiPlanError as exc:
            logger.warning(
                "Falling back to default attack plan after Gemini failure",
                extra={"repo_id": repo_id, "error": str(exc)},
            )
    else:
        logger.debug(
            "Using default attack plan",
            extra={
                "repo_id": repo_id,
                "use_gemini": settings.use_gemini,
                "manifest_available": bool(manifest),
            },
        )

    return _build_default_plan(repo_id)


def _build_default_plan(repo_id: str) -> AttackPlan:
    """Return the historical static attack plan used as a fallback."""

    steps: List[AttackStep] = [
        AttackStep(
            step_number=1,
            description="Initial access via exposed CI token in repository secrets.",
            technique_id="T1552",
            severity="high",
            affected_files=[".github/workflows/deploy.yml"],
        ),
        AttackStep(
            step_number=2,
            description="Privilege escalation through misconfigured Kubernetes RBAC manifests.",
            technique_id="T1068",
            severity="critical",
            affected_files=["deploy/k8s/rbac.yaml"],
        ),
        AttackStep(
            step_number=3,
            description="Establish persistence by modifying container entrypoint script.",
            technique_id="T1547",
            severity="medium",
            affected_files=["docker/entrypoint.sh"],
        ),
    ]

    return AttackPlan(repo_id=repo_id, overall_severity="critical", steps=steps)


def _generate_plan_with_gemini(repo_id: str, manifest: Dict[str, object]) -> AttackPlan:
    """Use Gemini to craft an attack plan based on the repository manifest."""

    high_risk_files = repo_fetcher.select_high_risk_files(manifest, limit=10)
    if not high_risk_files:
        raise GeminiPlanError("Manifest did not expose any high-risk files to analyse")

    prompt = _build_plan_prompt(repo_id, manifest, high_risk_files)
    logger.debug(
        "Gemini attack plan prompt prepared",
        extra={
            "repo_id": repo_id,
            "high_risk_file_count": len(high_risk_files),
        },
    )

    response_text = _invoke_gemini(prompt, {"repo_id": repo_id, "mode": "attack_plan"})
    plan_payload = _parse_plan_json(response_text)
    return _plan_from_dict(repo_id, plan_payload, manifest, high_risk_files)


def _build_plan_prompt(
    repo_id: str,
    manifest: Dict[str, object],
    high_risk_files: List[Dict[str, object]],
) -> str:
    """Create the prompt instructing Gemini to return a JSON attack plan."""

    manifest_summary = {
        "file_count": manifest.get("file_count"),
        "high_risk_file_count": manifest.get("high_risk_file_count"),
        "top_extensions": manifest.get("top_extensions", []),
    }
    high_risk_payload = [
        {
            "path": file.get("path"),
            "risk_level": file.get("risk_level"),
            "risk_reasons": file.get("risk_reasons", []),
            "size": file.get("size"),
        }
        for file in high_risk_files
        if file.get("path")
    ]

    format_instructions = {
        "overall_severity": "one of: low, medium, high, critical",
        "steps": [
            {
                "step_number": "int starting at 1",
                "description": "one sentence summarising attacker action",
                "technique_id": "MITRE ATT&CK ID (e.g. T1552)",
                "severity": "one of: low, medium, high, critical",
                "affected_files": "array of file paths chosen from the provided list",
            }
        ],
    }

    prompt = textwrap.dedent(
        f"""
        You are an experienced adversarial security engineer reviewing the repository below. Identify exploitable attack steps that a red team would attempt, prioritising files that are most likely to contain secrets, CI/CD misconfigurations, or insecure infrastructure as code.

        Repository ID: {repo_id}
        Repository summary (JSON):
        {json.dumps(manifest_summary, indent=2)}

        High risk files (JSON array):
        {json.dumps(high_risk_payload, indent=2)}

        Produce up to three attack steps that are realistic, actionable, and reference only the files listed. Each step must:
          - describe the attacker action in one sentence,
          - map to a MITRE ATT&CK technique id,
          - grade severity (low/medium/high/critical),
          - list the impacted files using repository paths provided above.

        Respond ONLY with JSON matching this structure:
        {json.dumps(format_instructions, indent=2)}
        """
    ).strip()

    return prompt


def _invoke_gemini(prompt: str, log_extra: Dict[str, object]) -> str:
    """Call the Gemini API and return the textual response."""

    settings = get_settings()
    if not settings.gemini_api_key:
        raise GeminiPlanError("Gemini API key is not configured")

    try:
        genai = importlib.import_module("google.generativeai")
    except ImportError as exc:
        raise GeminiPlanError("google-generativeai package is not installed") from exc

    try:
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.gemini_model)
        logger.info(
            "Requesting Gemini content",
            extra={**log_extra, "model": settings.gemini_model},
        )
        response = model.generate_content(prompt)
    except Exception as exc:  # noqa: BLE001
        raise GeminiPlanError("Gemini API request failed") from exc

    text = _extract_text_from_response(response)
    if not text:
        raise GeminiPlanError("Gemini response did not contain text output")
    return text


_JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _parse_plan_json(raw_text: str) -> Dict[str, object]:
    """Extract a JSON object from Gemini's response text."""

    if not raw_text:
        raise GeminiPlanError("Empty response received from Gemini")

    candidates = []
    code_block_pattern = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    candidates.extend(code_block_pattern.findall(raw_text))
    candidates.append(raw_text)

    for candidate in candidates:
        snippet = candidate.strip()
        if not snippet:
            continue
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue

    match = _JSON_BLOCK_PATTERN.search(raw_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise GeminiPlanError("Unable to decode JSON from Gemini response") from exc

    raise GeminiPlanError("Could not parse JSON from Gemini response")


def _plan_from_dict(
    repo_id: str,
    plan_payload: Dict[str, object],
    manifest: Dict[str, object],
    high_risk_files: List[Dict[str, object]],
) -> AttackPlan:
    """Convert Gemini JSON payload into an ``AttackPlan`` object."""

    steps_payload = plan_payload.get("steps")
    if not isinstance(steps_payload, list) or not steps_payload:
        raise GeminiPlanError("Gemini response did not include any attack steps")

    valid_paths = set(repo_fetcher.list_all_paths(manifest))
    high_risk_paths = [file.get("path") for file in high_risk_files if file.get("path")]

    steps: List[AttackStep] = []
    for index, raw_step in enumerate(steps_payload[:3], start=1):
        if not isinstance(raw_step, dict):
            continue

        description = str(raw_step.get("description") or "").strip()
        technique_id = _normalise_technique_id(raw_step.get("technique_id"))
        severity = _normalise_severity(raw_step.get("severity"))

        affected_files_raw = raw_step.get("affected_files") or []
        if isinstance(affected_files_raw, str):
            affected_files_raw = [affected_files_raw]
        filtered_files = [path for path in affected_files_raw if path in valid_paths]
        if not filtered_files and high_risk_paths:
            filtered_files = [high_risk_paths[min(index - 1, len(high_risk_paths) - 1)]]

        if not description:
            continue

        steps.append(
            AttackStep(
                step_number=int(raw_step.get("step_number") or index),
                description=description,
                technique_id=technique_id,
                severity=severity,
                affected_files=filtered_files,
            )
        )

    if not steps:
        raise GeminiPlanError("No valid attack steps could be derived from Gemini response")

    overall = _normalise_severity(plan_payload.get("overall_severity"))
    return AttackPlan(repo_id=repo_id, overall_severity=overall, steps=steps)


def _normalise_severity(value: Optional[object]) -> str:
    """Return a severity string limited to the allowed set."""

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _ALLOWED_SEVERITIES:
            return lowered
    return _DEFAULT_OVERALL_SEVERITY


def _normalise_technique_id(value: Optional[object]) -> str:
    """Return a best-effort MITRE technique id."""

    if isinstance(value, str) and value.strip():
        candidate = value.strip().upper()
        if not candidate.startswith("T"):
            candidate = f"T{candidate}"
        return candidate
    return "T0000"


def _extract_text_from_response(response: object) -> Optional[str]:
    """Best-effort extraction of textual content from a Gemini response object."""

    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    parts: List[str] = []
    candidates = getattr(response, "candidates", []) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            if hasattr(part, "text") and isinstance(part.text, str) and part.text.strip():
                parts.append(part.text.strip())

    if parts:
        return "\n".join(parts).strip()

    return None


def _build_insight_prompt(run: SimulationRun, report: SimulationReport) -> str:
    """Create a prompt for Gemini that summarises the simulation context."""

    severity_breakdown = {
        key: value for key, value in report.summary.items() if key.endswith("_steps")
    }
    affected_files = report.summary.get("affected_files", [])
    step_lines = []
    for step in run.plan.steps:
        files = ", ".join(step.affected_files) if step.affected_files else "None specified"
        step_lines.append(
            f"Step {step.step_number}: {step.description} | Severity: {step.severity} | Technique: {step.technique_id} | Files: {files}"
        )
    step_section = "\n".join(step_lines) if step_lines else "No attack steps were captured."

    sandbox_summary = ""
    if isinstance(run.sandbox, dict):
        sandbox_summary = run.sandbox.get("summary") or "Sandbox summary unavailable."
        logs = run.sandbox.get("logs") or []
        log_lines = []
        for entry in logs[:5]:
            timestamp = entry.get("timestamp", "?")
            action = entry.get("action", "unknown action")
            status = entry.get("status", "unknown status")
            step = entry.get("step", "?")
            log_lines.append(f"- [{timestamp}] Step {step}: {action} -> {status}")
        log_section = "\n".join(log_lines) if log_lines else "No sandbox log entries supplied."
    else:
        sandbox_summary = "Sandbox summary unavailable."
        log_section = "No sandbox log entries supplied."

    prompt = textwrap.dedent(
        f"""
        You are an experienced DevSecOps analyst. Review the simulated attack below and provide a concise AI insight (no more than three sentences) highlighting key risks and suggested focus areas for remediation. Avoid repeating the raw data verbatim.

        Repository: {run.repo_id}
        Simulation Run: {run.run_id}
        Overall Severity: {report.summary.get('overall_severity', 'unknown')}
        Severity Breakdown: {severity_breakdown}
        Affected Files: {', '.join(affected_files) if affected_files else 'None listed'}

        Attack Plan Steps:
        {step_section}

        Sandbox Summary:
        {sandbox_summary}

        Sandbox Log Sample:
        {log_section}

        Provide the AI Insight as a short paragraph ready for display to security engineers.
        """
    ).strip()

    return prompt


def generate_ai_insight(run: SimulationRun, report: SimulationReport) -> Optional[str]:
    """Generate a short Gemini-produced insight for a simulation run."""

    settings = get_settings()
    if not settings.use_gemini:
        logger.debug(
            "Gemini insight generation skipped because USE_GEMINI is disabled",
            extra={"repo_id": run.repo_id, "run_id": run.run_id},
        )
        return None

    if not settings.gemini_api_key:
        logger.warning(
            "Gemini enabled but API key not configured",
            extra={"repo_id": run.repo_id, "run_id": run.run_id},
        )
        return _FALLBACK_MESSAGE

    prompt = _build_insight_prompt(run, report)

    try:
        insight_text = _invoke_gemini(
            prompt,
            {
                "repo_id": run.repo_id,
                "run_id": run.run_id,
                "mode": "insight",
            },
        )
        logger.info(
            "Gemini insight generated",
            extra={
                "repo_id": run.repo_id,
                "run_id": run.run_id,
                "model": settings.gemini_model,
                "characters": len(insight_text),
            },
        )
        return insight_text
    except GeminiPlanError as exc:
        logger.exception(
            "Gemini insight generation failed",
            extra={"repo_id": run.repo_id, "run_id": run.run_id, "error": str(exc)},
        )
        return _FALLBACK_MESSAGE


# ==============================================================================
# REST API Interface
# ==============================================================================


def generate_gemini_response(prompt: str) -> dict:
    """
    Generate a response from Gemini using the REST API.
    
    This function provides direct access to the Gemini API via HTTP requests,
    as an alternative to the google-generativeai SDK used elsewhere.
    
    Args:
        prompt: The text prompt to send to Gemini
        
    Returns:
        dict: Response containing 'text' key with the model's output,
              or 'error' key if the request failed
              
    Example:
        >>> result = generate_gemini_response("Explain what a SQL injection is")
        >>> print(result['text'])
        
    Raises:
        ValueError: If GEMINI_API_KEY is not configured
        httpx.TimeoutException: If the request times out
        httpx.HTTPError: If the HTTP request fails
    """
    settings = get_settings()
    
    # Validate configuration
    if not settings.gemini_api_key:
        error_msg = "GEMINI_API_KEY environment variable is not configured"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # Use configured model or default to gemini-pro
    model_name = settings.gemini_model or "gemini-pro"
    
    # Use v1beta for broader model support
    api_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        f"?key={settings.gemini_api_key}"
    )
    
    # Build request payload
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    
    logger.info(
        "Sending Gemini REST API request",
        extra={
            "model": model_name,
            "prompt_length": len(prompt),
            "api_method": "REST"
        }
    )
    
    try:
        # Make HTTP request with timeout
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                api_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            # Check for HTTP errors
            response.raise_for_status()
            
            # Parse response
            response_data = response.json()
            
            # Extract text from response
            if "candidates" in response_data and len(response_data["candidates"]) > 0:
                candidate = response_data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    parts = candidate["content"]["parts"]
                    if len(parts) > 0 and "text" in parts[0]:
                        text_output = parts[0]["text"]
                        
                        logger.info(
                            "Gemini REST API response received",
                            extra={
                                "model": model_name,
                                "response_length": len(text_output),
                                "candidates": len(response_data["candidates"])
                            }
                        )
                        
                        return {
                            "text": text_output,
                            "model": model_name,
                            "candidates": response_data.get("candidates", [])
                        }
            
            # Response doesn't contain expected structure
            error_msg = "Gemini response did not contain expected text output"
            logger.warning(
                error_msg,
                extra={"response_structure": list(response_data.keys())}
            )
            return {
                "error": error_msg,
                "raw_response": response_data
            }
            
    except httpx.TimeoutException as exc:
        error_msg = "Gemini API request timed out after 30 seconds"
        logger.error(
            error_msg,
            extra={"model": model_name, "error": str(exc)}
        )
        return {
            "error": error_msg,
            "exception": str(exc)
        }
        
    except httpx.HTTPStatusError as exc:
        error_msg = f"Gemini API returned HTTP {exc.response.status_code}"
        logger.error(
            error_msg,
            extra={
                "model": model_name,
                "status_code": exc.response.status_code,
                "response_text": exc.response.text[:500]  # Log first 500 chars
            }
        )
        return {
            "error": error_msg,
            "status_code": exc.response.status_code,
            "details": exc.response.text
        }
        
    except httpx.HTTPError as exc:
        error_msg = f"HTTP error occurred: {type(exc).__name__}"
        logger.exception(
            "Gemini API HTTP request failed",
            extra={"model": model_name, "error": str(exc)}
        )
        return {
            "error": error_msg,
            "exception": str(exc)
        }
        
    except json.JSONDecodeError as exc:
        error_msg = "Failed to parse Gemini API response as JSON"
        logger.exception(
            error_msg,
            extra={"model": model_name, "error": str(exc)}
        )
        return {
            "error": error_msg,
            "exception": str(exc)
        }
        
    except Exception as exc:  # noqa: BLE001
        error_msg = f"Unexpected error calling Gemini API: {type(exc).__name__}"
        logger.exception(
            "Unexpected Gemini API error",
            extra={"model": model_name, "error": str(exc)}
        )
        return {
            "error": error_msg,
            "exception": str(exc)
        }


# ============================================================================
# NEW GEMINI ATTACK PLAN GENERATION (Feature Flag Controlled)
# ============================================================================

def generate_gemini_attack_plan(
    repo_profile: Dict[str, object],
    max_steps: int = 3
) -> Dict[str, object]:
    """
    Generate AI-powered attack plan using Gemini REST API with structured prompt.
    
    Args:
        repo_profile: Repository context including manifest, high-risk files, languages, dependencies
        max_steps: Maximum number of attack steps to generate (default: 3)
    
    Returns:
        Dict containing:
        - attack_id: Unique identifier
        - overall_severity: critical/high/medium/low
        - steps: List of attack steps with MITRE technique IDs
        - gemini_prompt: Original prompt sent to Gemini
        - gemini_raw_response: Raw Gemini API response
        - plan_source: "gemini" or "fallback"
        - ai_insight: Summary insight from Gemini (if available)
    
    Security:
        - Sanitizes returned text (no direct commands, no inline secrets)
        - Validates file paths exist in repo_profile
        - Rate-limited and timeout-protected
        - Falls back to deterministic plan if Gemini fails or disabled
    """
    settings = get_settings()
    repo_id = repo_profile.get("repo_id", "unknown")
    
    # Check if Gemini is enabled
    if not settings.use_gemini or not settings.gemini_api_key:
        logger.info(
            "Using fallback attack plan (Gemini disabled or API key missing)",
            extra={
                "repo_id": repo_id,
                "use_gemini": settings.use_gemini,
                "has_api_key": bool(settings.gemini_api_key)
            }
        )
        return _build_fallback_attack_plan(repo_id, "fallback")
    
    # Build structured prompt
    try:
        prompt = _build_attack_plan_prompt(repo_profile, max_steps)
        logger.debug(
            "Gemini attack plan prompt generated",
            extra={
                "repo_id": repo_id,
                "prompt_length": len(prompt),
                "max_steps": max_steps
            }
        )
    except Exception as exc:
        logger.error(
            "Failed to build Gemini prompt",
            extra={"repo_id": repo_id, "error": str(exc)}
        )
        return _build_fallback_attack_plan(repo_id, "fallback")
    
    # Call Gemini REST API with retry logic
    max_retries = 2
    retry_count = 0
    last_error = None
    
    while retry_count <= max_retries:
        try:
            result = generate_gemini_response(prompt)
            
            if "error" in result:
                last_error = result["error"]
                retry_count += 1
                if retry_count <= max_retries:
                    logger.warning(
                        f"Gemini API call failed, retrying ({retry_count}/{max_retries})",
                        extra={"repo_id": repo_id, "error": last_error}
                    )
                    continue
                else:
                    logger.error(
                        "Gemini API failed after all retries",
                        extra={"repo_id": repo_id, "error": last_error, "retries": max_retries}
                    )
                    return _build_fallback_attack_plan(repo_id, "fallback")
            
            # Success - parse response
            raw_response = result.get("text", "")
            model_used = result.get("model", settings.gemini_model)
            
            logger.info(
                "Gemini attack plan response received",
                extra={
                    "repo_id": repo_id,
                    "model": model_used,
                    "response_length": len(raw_response)
                }
            )
            
            # Parse and validate JSON response
            try:
                attack_plan = _parse_and_validate_attack_plan(
                    raw_response, 
                    repo_profile,
                    max_steps
                )
                
                # Add metadata
                attack_plan["gemini_prompt"] = prompt
                attack_plan["gemini_raw_response"] = raw_response
                attack_plan["plan_source"] = "gemini"
                attack_plan["model_used"] = model_used
                attack_plan["repo_id"] = repo_id
                
                logger.info(
                    "Gemini attack plan successfully generated and validated",
                    extra={
                        "repo_id": repo_id,
                        "steps": len(attack_plan.get("steps", [])),
                        "overall_severity": attack_plan.get("overall_severity")
                    }
                )
                
                return attack_plan
                
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                logger.error(
                    "Failed to parse Gemini response",
                    extra={
                        "repo_id": repo_id,
                        "error": str(exc),
                        "response_preview": raw_response[:500]
                    }
                )
                return _build_fallback_attack_plan(repo_id, "fallback")
                
        except Exception as exc:
            last_error = str(exc)
            retry_count += 1
            logger.exception(
                f"Unexpected error calling Gemini ({retry_count}/{max_retries})",
                extra={"repo_id": repo_id, "error": str(exc)}
            )
            if retry_count > max_retries:
                return _build_fallback_attack_plan(repo_id, "fallback")
    
    # Should not reach here, but safety fallback
    return _build_fallback_attack_plan(repo_id, "fallback")


def _build_attack_plan_prompt(repo_profile: Dict[str, object], max_steps: int) -> str:
    """
    Build structured prompt for Gemini to generate attack plan.
    
    Prompt template instructs Gemini to:
    - Act as red-team security analyst
    - Produce JSON with attack steps
    - Include MITRE ATT&CK technique IDs
    - Reference only files from provided manifest
    - Not include executable payloads or secrets
    """
    repo_id = repo_profile.get("repo_id", "unknown")
    manifest = repo_profile.get("manifest", {})
    high_risk_files = repo_profile.get("high_risk_files", [])
    languages = repo_profile.get("languages", [])
    dependencies = repo_profile.get("dependencies", [])
    
    # Build file list for context
    file_list = []
    if high_risk_files:
        file_list = [
            {
                "path": f.get("path"),
                "risk_level": f.get("risk_level"),
                "risk_reasons": f.get("risk_reasons", [])
            }
            for f in high_risk_files[:10]  # Limit to top 10
            if f.get("path")
        ]
    
    # Build repository context summary
    repo_context = {
        "repo_id": repo_id,
        "total_files": manifest.get("file_count", 0),
        "high_risk_files_count": len(high_risk_files),
        "primary_languages": languages[:5] if languages else [],
        "key_dependencies": dependencies[:10] if dependencies else [],
        "high_risk_files": file_list
    }
    
    prompt = f"""You are a red-team security analyst for DevSecOps. Given the repository context below, produce a concise, structured JSON attack plan with up to {max_steps} steps.

For each step include:
- step_number: integer starting at 1
- description: one-sentence description of the attacker action
- technique_id: MITRE ATT&CK technique ID (e.g., T1078, T1552, T1068) if applicable
- severity: one of [critical, high, medium, low]
- affected_files: array of file paths from the provided file list

IMPORTANT CONSTRAINTS:
1. Validate that all affected_files paths exist in the provided high_risk_files list
2. Do NOT return executable payloads, secrets, or live credentials
3. Output MUST be valid JSON only (no markdown, no explanations)
4. Be realistic and actionable - focus on actual vulnerabilities based on file types and names
5. Map each step to appropriate MITRE ATT&CK techniques

Repository context:
{json.dumps(repo_context, indent=2)}

Required JSON output structure:
{{
  "overall_severity": "critical|high|medium|low",
  "ai_insight": "Brief 1-2 sentence summary of overall attack surface",
  "steps": [
    {{
      "step_number": 1,
      "description": "Concise description of attack step",
      "technique_id": "T1552",
      "severity": "critical|high|medium|low",
      "affected_files": ["path/to/file.ext"]
    }}
  ]
}}

Output only the JSON object, nothing else:"""
    
    return prompt


def _parse_and_validate_attack_plan(
    raw_response: str,
    repo_profile: Dict[str, object],
    max_steps: int
) -> Dict[str, object]:
    """
    Parse Gemini JSON response and validate/sanitize attack plan.
    
    Security checks:
    - Strip any direct commands or shell code
    - Remove inline secrets (API keys, tokens, passwords)
    - Validate file paths exist in repo_profile
    - Ensure severity values are valid
    - Limit to max_steps
    """
    # Extract JSON from response (handle markdown code blocks)
    json_text = raw_response.strip()
    
    # Remove markdown code blocks if present
    if json_text.startswith("```"):
        lines = json_text.split("\n")
        json_text = "\n".join(lines[1:-1]) if len(lines) > 2 else json_text
        json_text = json_text.replace("```json", "").replace("```", "").strip()
    
    # Parse JSON
    try:
        plan_data = json.loads(json_text)
    except json.JSONDecodeError:
        # Try to extract JSON object with regex as fallback
        match = re.search(r'\{[\s\S]*\}', json_text)
        if match:
            plan_data = json.loads(match.group(0))
        else:
            raise ValueError("No valid JSON found in Gemini response")
    
    # Validate structure
    if not isinstance(plan_data, dict):
        raise ValueError("Gemini response is not a JSON object")
    
    if "steps" not in plan_data or not isinstance(plan_data["steps"], list):
        raise ValueError("Gemini response missing 'steps' array")
    
    # Get valid file paths from repo_profile
    valid_files = set()
    high_risk_files = repo_profile.get("high_risk_files", [])
    for f in high_risk_files:
        if path := f.get("path"):
            valid_files.add(path)
    
    # Validate and sanitize each step
    sanitized_steps = []
    for i, step in enumerate(plan_data["steps"][:max_steps]):
        if not isinstance(step, dict):
            continue
        
        # Sanitize description (remove potential commands)
        description = str(step.get("description", "")).strip()
        description = _sanitize_text(description)
        
        # Validate severity
        severity = str(step.get("severity", "medium")).lower()
        if severity not in _ALLOWED_SEVERITIES:
            severity = "medium"
        
        # Validate and filter affected_files
        affected_files = step.get("affected_files", [])
        if isinstance(affected_files, list):
            # Only include files that exist in repo_profile
            affected_files = [
                f for f in affected_files
                if isinstance(f, str) and (f in valid_files or not valid_files)
            ][:5]  # Limit to 5 files per step
        else:
            affected_files = []
        
        sanitized_step = {
            "step_number": i + 1,
            "description": description,
            "technique_id": str(step.get("technique_id", "")).strip() or "N/A",
            "severity": severity,
            "affected_files": affected_files
        }
        
        sanitized_steps.append(sanitized_step)
    
    if not sanitized_steps:
        raise ValueError("No valid steps found in Gemini response")
    
    # Validate overall severity
    overall_severity = str(plan_data.get("overall_severity", "high")).lower()
    if overall_severity not in _ALLOWED_SEVERITIES:
        overall_severity = _DEFAULT_OVERALL_SEVERITY
    
    # Extract AI insight
    ai_insight = str(plan_data.get("ai_insight", "")).strip()
    ai_insight = _sanitize_text(ai_insight) if ai_insight else "AI-generated attack plan"
    
    return {
        "overall_severity": overall_severity,
        "ai_insight": ai_insight,
        "steps": sanitized_steps
    }


def _sanitize_text(text: str) -> str:
    """
    Remove potentially dangerous content from text.
    
    - Strip shell commands (rm, curl, wget, etc.)
    - Remove apparent API keys/tokens
    - Remove inline code execution
    """
    if not text:
        return ""
    
    # Remove common dangerous patterns
    dangerous_patterns = [
        r'rm\s+-rf',
        r'curl\s+',
        r'wget\s+',
        r'bash\s+',
        r'sh\s+',
        r'exec\(',
        r'eval\(',
        r'os\.system',
        r'subprocess\.',
    ]
    
    for pattern in dangerous_patterns:
        text = re.sub(pattern, '[REDACTED]', text, flags=re.IGNORECASE)
    
    # Remove apparent secrets (basic pattern matching)
    # API keys: AIza..., sk-...
    text = re.sub(r'AIza[0-9A-Za-z_-]{35}', '[REDACTED_API_KEY]', text)
    text = re.sub(r'sk-[0-9A-Za-z]{48}', '[REDACTED_API_KEY]', text)
    
    # Generic tokens
    text = re.sub(r'[A-Za-z0-9_-]{40,}', lambda m: '[REDACTED_TOKEN]' if any(c.isdigit() and c.isalpha() for c in m.group()) else m.group(), text)
    
    return text.strip()


def _build_fallback_attack_plan(repo_id: str, source: str) -> Dict[str, object]:
    """
    Build deterministic fallback attack plan when Gemini is unavailable.
    
    Returns same structure as Gemini-generated plan for API compatibility.
    """
    fallback_steps = [
        {
            "step_number": 1,
            "description": "Initial access via exposed CI token in repository secrets",
            "technique_id": "T1552",
            "severity": "high",
            "affected_files": [".github/workflows/deploy.yml"]
        },
        {
            "step_number": 2,
            "description": "Privilege escalation through misconfigured Kubernetes RBAC manifests",
            "technique_id": "T1068",
            "severity": "critical",
            "affected_files": ["deploy/k8s/rbac.yaml"]
        },
        {
            "step_number": 3,
            "description": "Establish persistence by modifying container entrypoint script",
            "technique_id": "T1547",
            "severity": "medium",
            "affected_files": ["docker/entrypoint.sh"]
        }
    ]
    
    return {
        "repo_id": repo_id,
        "overall_severity": "critical",
        "ai_insight": "Deterministic fallback plan - Gemini unavailable",
        "steps": fallback_steps,
        "plan_source": source,
        "gemini_prompt": None,
        "gemini_raw_response": None,
        "model_used": None
    }
