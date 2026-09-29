# Environment Setup Guide

## 1. Activate the Virtual Environment

```bash
# Enter the project directory
cd /root/ClydeCLI

# Activate the virtual environment
source .venv/bin/activate

# Confirm the Python version
python --version  # Should show Python 3.14.x
```

## 2. Configure the GLM API Key

### Option 1: Environment variable (recommended for testing)

```bash
# Temporary (valid for the current session)
export GLM_API_KEY="your_api_key_here"

# Permanent (add to ~/.bashrc)
echo 'export GLM_API_KEY="your_api_key_here"' >> ~/.bashrc
source ~/.bashrc
```

### Option 2: .env file (recommended for development)

```bash
# Create a .env file in the project root
cat > .env << 'EOF'
# GLM API Configuration
GLM_API_KEY=your_api_key_here
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_DEFAULT_MODEL=glm-4

# Optional: Other APIs
# ANTHROPIC_API_KEY=your_anthropic_key
# OPENAI_API_KEY=your_openai_key
EOF

# The .env file is in .gitignore and will not be committed to Git
```

## 3. GLM API Information

### API Endpoint
- **Base URL**: `https://open.bigmodel.cn/api/paas/v4`
- **Authentication**: Bearer Token (API Key)
- **Documentation**: https://open.bigmodel.cn/dev/api

### Available Models
- `glm-4` - Latest GLM-4 model (recommended)
- `glm-4-flash` - Fast version
- `glm-3-turbo` - GLM-3 Turbo

### API Call Example (Python)
```python
from zhipuai import ZhipuAI

client = ZhipuAI(api_key="your_api_key")

response = client.chat.completions.create(
    model="glm-4",
    messages=[
        {"role": "user", "content": "Hello"}
    ]
)
print(response.choices[0].message.content)
```

## 4. Verify the Configuration

### Test Environment Variables
```bash
# Check whether the environment variable is set
echo $GLM_API_KEY

# If using a .env file, Python loads it automatically
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('GLM_API_KEY'))"
```

## 5. Next Steps

Once configuration is complete, the remaining setup steps are:
1. Create `requirements.txt` and `setup.py`
2. Install dependencies: `uv pip install -e .`
3. Create the config file: `~/.clyde/config.json`
4. Test the GLM API connection

---

## FAQ

### Q: Where do I get an API Key?
A: Visit https://open.bigmodel.cn/ and register an account to obtain one

### Q: How do I get an API Key?
A:
1. Log in to the Zhipu Open Platform
2. Go to the "API Keys" page
3. Create a new API Key

### Q: Is there a free quota?
A: New users usually receive a free trial quota; see the official website for details

---

## Checklist

Complete the following steps:

1. ✅ **Activate the virtual environment**:
   ```bash
   source .venv/bin/activate
   ```

2. ✅ **Configure the API Key** (choose one):
   - Option 1: `export GLM_API_KEY="your_key"`
   - Option 2: Create a `.env` file and add the key to it

3. ✅ **Continue with the next steps** in section 5 once the above is done
