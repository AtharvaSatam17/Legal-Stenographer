// pages/api/auth/logout.js
import { serialize } from 'cookie';

export default function handler(req, res) {
  const COGNITO_DOMAIN = process.env.COGNITO_DOMAIN; // e.g. https://ap-south-1iuh4zsyrc.auth.ap-south-1.amazoncognito.com
  const COGNITO_CLIENT_ID = process.env.COGNITO_CLIENT_ID;
  const LOGOUT_URI = process.env.LOGOUT_URI || 'http://localhost:3000/';
  const isProd = process.env.NODE_ENV === 'production';

  if (!COGNITO_DOMAIN || !COGNITO_CLIENT_ID) {
    return res.status(500).json({ error: 'Missing Cognito environment variables' });
  }

  // 1. Clear auth cookies
  res.setHeader('Set-Cookie', [
    serialize('id_token', '', {
      httpOnly: true,
      secure: isProd,
      path: '/',
      expires: new Date(0),
    }),
    serialize('access_token', '', {
      httpOnly: true,
      secure: isProd,
      path: '/',
      expires: new Date(0),
    }),
  ]);

  // 2. Build Cognito logout URL
  const cognitoLogoutUrl = `${COGNITO_DOMAIN}/logout?client_id=${COGNITO_CLIENT_ID}&logout_uri=${encodeURIComponent(
    LOGOUT_URI
  )}`;

  console.log('Redirecting to:', cognitoLogoutUrl);

  // 3. Redirect user to Cognito hosted UI logout
  res.writeHead(302, { Location: cognitoLogoutUrl });
  res.end();
}
