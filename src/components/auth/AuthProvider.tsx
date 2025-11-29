'use client';

import { Auth0Provider, useAuth0 } from '@auth0/auth0-react';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { setTokenGetter } from '@/lib/api';

function TokenSetup({ children }: { children: React.ReactNode }) {
  const { getAccessTokenSilently, isAuthenticated } = useAuth0();

  useEffect(() => {
    if (isAuthenticated) {
      setTokenGetter(async () => {
        try {
          return await getAccessTokenSilently({
            authorizationParams: {
              scope: 'openid profile email'
            }
          });
        } catch (err) {
          console.error('Error getting access token:', err);
          return '';
        }
      });
    }
  }, [getAccessTokenSilently, isAuthenticated]);

  return <>{children}</>;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  const domain = process.env.NEXT_PUBLIC_AUTH0_DOMAIN!;
  const clientId = process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID!;

  const onRedirectCallback = (appState?: any) => {
    router.push(appState?.returnTo || '/demo');
  };

  return (
    <Auth0Provider
      domain={domain}
      clientId={clientId}
      authorizationParams={{
        redirect_uri: typeof window !== 'undefined' ? window.location.origin : '',
        scope: 'openid profile email'
      }}
      onRedirectCallback={onRedirectCallback}
      cacheLocation="localstorage"
      useRefreshTokens={true}
    >
      <TokenSetup>{children}</TokenSetup>
    </Auth0Provider>
  );
}
