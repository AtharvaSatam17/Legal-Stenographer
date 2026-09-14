// lib/withAuth.js
import { getUserFromRequest } from './auth';

export function withAuth(gssp) {
  return async (context) => {
    const user = await getUserFromRequest(context.req);

    if (!user) {
        const cognitoDomain = process.env.COGNITO_DOMAIN;
        const clientId = process.env.COGNITO_CLIENT_ID;
        const redirectUri = encodeURIComponent(process.env.CALLBACK_URI); 
  
        const loginUrl = `${cognitoDomain}/login?client_id=${clientId}&response_type=code&scope=openid+phone+email&redirect_uri=${redirectUri}`;
  
        return {
          redirect: {
            destination: loginUrl,
            permanent: false,
          },
        };
      }

    // Optionally add user to the props
    context.user = user;

    const gsspData = await gssp(context);

    return {
      props: {
        ...gsspData.props,
        user, // inject user into all pages
      },
    };
  };
}
