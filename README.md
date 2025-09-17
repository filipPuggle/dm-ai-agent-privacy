# Instagram Webhook Bot

A Flask-based webhook server that automatically responds to Instagram messages by the context using the Instagram Graph API.

## Features

- ✅ Receives Instagram webhook notifications
- ✅ Automatically responds to text messages
- ✅ Uses Instagram Graph API for messaging
- ✅ Environment variable configuration
- ✅ Railway deployment ready

## Local Development

### Prerequisites

- Python 3.12+
- Instagram Business Account
- Facebook App with Instagram Graph API permissions

### Setup

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd dm-ai-agent-privacy
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   Create a `.env` file in the project root:
   ```env
   GRAPH_API_ACCESS_TOKEN=your_graph_api_token
   INSTAGRAM_BUSINESS_ACCOUNT_ID=your_instagram_business_account_id
   INSTAGRAM_ACCESS_TOKEN=your_instagram_access_token
   IG_VERIFY_TOKEN=your_webhook_verify_token
   IG_APP_SECRET=your_app_secret
   ```

5. **Run the development server**
   ```bash
   flask run --host=0.0.0.0 --port=3000
   ```

## Railway Deployment

### Prerequisites

- Railway account
- GitHub repository with your code

### Deployment Steps

1. **Connect your repository to Railway**
   - Go to [Railway](https://railway.app)
   - Create a new project
   - Connect your GitHub repository

2. **Set environment variables in Railway**
   - Go to your project's Variables tab
   - Add the same environment variables as in the `.env` file:
     - `GRAPH_API_ACCESS_TOKEN`
     - `INSTAGRAM_BUSINESS_ACCOUNT_ID`
     - `INSTAGRAM_ACCESS_TOKEN`
     - `IG_VERIFY_TOKEN`
     - `IG_APP_SECRET`

3. **Deploy**
   - Railway will automatically detect the Python project
   - It will use the `requirements.txt` and `Procfile` for deployment
   - The app will be available at your Railway URL

### Configuration Files

- `requirements.txt` - Python dependencies
- `Procfile` - Process definition for Railway
- `railway.json` - Railway-specific configuration
- `nixpacks.toml` - Nixpacks build configuration
- `runtime.txt` - Python version specification

## Webhook Configuration

### Instagram App Setup

1. Go to [Facebook Developers](https://developers.facebook.com)
2. Navigate to your app
3. Go to **Instagram** → **Basic Display** or **Instagram Graph API**
4. Configure webhook URL: `https://your-railway-url.railway.app/webhook`
5. Set verify token to match your `IG_VERIFY_TOKEN`
6. Subscribe to these events:
   - `messages`
   - `messaging_postbacks`
   - `messaging_reactions`

### Testing

Send a message to your Instagram Business account, and you should receive "Hello, World!" as a response.

## API Endpoints

- `GET /` - Health check
- `GET /privacy_policy` - Privacy policy page
- `POST /webhook` - Instagram webhook endpoint
- `GET /instagram/callback` - OAuth callback endpoint

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GRAPH_API_ACCESS_TOKEN` | Facebook Graph API access token | Yes |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Instagram Business Account ID | Yes |
| `INSTAGRAM_ACCESS_TOKEN` | Instagram access token | Yes |
| `IG_VERIFY_TOKEN` | Webhook verification token | Yes |
| `IG_APP_SECRET` | Instagram app secret | Yes |

## Troubleshooting

### Common Issues

1. **"Invalid OAuth access token"**
   - Your access token has expired
   - Generate a new token in Facebook Developers Console

2. **Webhook not receiving messages**
   - Check webhook URL configuration
   - Verify webhook subscription events
   - Ensure verify token matches

3. **Messages not being sent**
   - Check Instagram Business Account permissions
   - Verify access token has `instagram_business_manage_messages` permission

## License

MIT License 
