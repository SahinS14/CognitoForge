# 🚀 CognitoForge - Auth0 Integration Setup Guide

## 📋 Prerequisites

- Node.js 18+ 
- npm or yarn
- Auth0 account (free tier available)

## 🛠️ Installation Steps

### 1. Install Dependencies

```bash
# Navigate to the frontend project
cd frontend

# Install all dependencies
npm install

# Or with yarn
yarn install
```

### 2. Auth0 Dashboard Setup

#### Create Auth0 Application
1. Go to [Auth0 Dashboard](https://auth0.com)
2. Sign up or sign in to your account
3. Go to **Applications** → **Create Application**
4. Choose **Single Page Web Applications**
5. Name it "CognitoForge"

#### Configure Application Settings
In your Auth0 application settings, add these URLs:

**Allowed Callback URLs:**
```
http://localhost:3000/api/auth/callback
```

**Allowed Logout URLs:**
```
http://localhost:3000
```

**Allowed Web Origins:**
```
http://localhost:3000
```

### 3. Environment Configuration

#### Create Environment File
Copy `.env.local.example` to `.env.local`:

```bash
cd frontend
cp .env.local.example .env.local
```

#### Fill in Auth0 Credentials
Edit `.env.local` with your Auth0 application details:

```bash
# Generate a secret key
AUTH0_SECRET='your-32-character-secret-key'

# Your app URL
AUTH0_BASE_URL='http://localhost:3000'

# From Auth0 Dashboard → Applications → CognitoForge → Settings
AUTH0_ISSUER_BASE_URL='https://YOUR_DOMAIN.auth0.com'
AUTH0_CLIENT_ID='your-client-id'
AUTH0_CLIENT_SECRET='your-client-secret'

# Optional: Custom scopes
AUTH0_SCOPE='openid profile email'
```

**To generate AUTH0_SECRET:**
```bash
# On Windows (PowerShell)
[System.Web.Security.Membership]::GeneratePassword(32, 0)

# On macOS/Linux
openssl rand -hex 32
```

### 4. Social Login Setup (Optional)

#### Google OAuth
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google+ API
4. Create OAuth 2.0 credentials
5. Add to Auth0: **Authentication** → **Social** → **Google**

#### GitHub OAuth
1. Go to GitHub **Settings** → **Developer settings** → **OAuth Apps**
2. Create new OAuth App
3. Add to Auth0: **Authentication** → **Social** → **GitHub**

### 5. Run the Application

```bash
# Start development server
cd frontend
npm run dev

# Or with yarn
yarn dev
```

Visit `http://localhost:3000` to see your application!

## 🔧 Features Included

### ✅ Authentication Components
- **LoginButton** - Redirects to Auth0 login
- **LogoutButton** - Handles secure logout
- **AuthButton** - Smart login/logout toggle
- **UserProfile** - Displays user information
- **ProtectedContent** - Wraps content requiring auth

### ✅ Protected Routes
- Demo page requires authentication
- Automatic redirects for unauthenticated users
- Seamless user experience

### ✅ UI Components (shadcn/ui)
- **Button** - Multiple variants including brand styling
- **Progress** - For analysis progress indicators
- **Motion** - Framer Motion animations
- **Icons** - Lucide React icon library

### ✅ Styling
- **TailwindCSS** - Utility-first CSS framework
- **Dark Theme** - Modern dark UI with purple accent
- **Glass Morphism** - Modern glassmorphism effects
- **Responsive Design** - Mobile-first approach

## 🎨 Customization

### Brand Colors
Update `tailwind.config.js` to customize colors:

```javascript
brand: {
  primary: "#7c5cff",    // Purple primary
  accent: "#00d4aa",     // Teal accent  
  background: "#0a0612", // Dark background
  surface: "#0f0b1a",    // Card surfaces
}
```

### Auth0 User Metadata
Add custom user fields in Auth0 Actions:

```javascript
// Auth0 Action - Post Login
exports.onExecutePostLogin = async (event, api) => {
  const namespace = 'https://cognitoforge.com/';
  
  api.idToken.setCustomClaim(namespace + 'roles', event.user.app_metadata?.roles || []);
  api.idToken.setCustomClaim(namespace + 'permissions', event.user.app_metadata?.permissions || []);
};
```

## 🔒 Security Best Practices

### Environment Security
- Never commit `.env.local` to version control
- Use different secrets for staging/production
- Rotate secrets regularly

### Auth0 Security
- Enable MFA for admin accounts
- Use Rules/Actions for additional security
- Monitor login attempts and anomalies
- Set up proper CORS origins

### Application Security
- Validate user input on both client and server
- Use HTTPS in production
- Implement proper session management
- Regular security audits

## 📦 Deployment

### Vercel (Recommended)
1. Connect your GitHub repository to Vercel
2. Add environment variables in Vercel dashboard
3. Update Auth0 URLs to production domain
4. Deploy!

### Other Platforms
Update these Auth0 settings for your production domain:
- Allowed Callback URLs: `https://yourdomain.com/api/auth/callback`
- Allowed Logout URLs: `https://yourdomain.com`
- Allowed Web Origins: `https://yourdomain.com`

## 🐛 Troubleshooting

### Common Issues

**"Cannot find module '@auth0/nextjs-auth0'"**
```bash
npm install @auth0/nextjs-auth0
```

**"Invalid state parameter"**
- Check AUTH0_SECRET is set correctly
- Ensure AUTH0_BASE_URL matches your actual URL

**"Access denied"**
- Verify Auth0 application URLs are correct
- Check Auth0 application type (should be SPA)

**Styling issues**
```bash
npm install tailwindcss @tailwindcss/typography postcss autoprefixer
```

### Debug Mode
Add to `.env.local` for detailed logs:
```bash
DEBUG=auth0*
AUTH0_DEBUG=true
```

## 📞 Support

- **Auth0 Documentation**: https://auth0.com/docs
- **Next.js Documentation**: https://nextjs.org/docs
- **TailwindCSS Documentation**: https://tailwindcss.com/docs
- **shadcn/ui Documentation**: https://ui.shadcn.com

## 🎯 Next Steps

1. **Custom User Dashboard** - Build user profile management
2. **Role-Based Access** - Implement user roles and permissions
3. **API Integration** - Connect to your backend services
4. **Analytics** - Add user behavior tracking
5. **Testing** - Implement comprehensive test suite

---

**🎉 Congratulations!** You now have a fully functional Next.js application with Auth0 authentication, modern UI components, and a beautiful dark theme perfect for your CognitoForge security platform.