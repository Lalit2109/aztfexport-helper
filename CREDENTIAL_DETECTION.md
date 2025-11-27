# Automatic Credential Detection

## Yes, it automatically checks which credentials to use!

The code uses **`DefaultAzureCredential()`** which automatically tries multiple authentication methods in order until it finds one that works.

## How It Works

### Automatic Detection Order

`DefaultAzureCredential()` tries these methods **in this exact order**:

1. **Environment Variables** (if set)
   - `AZURE_CLIENT_ID`
   - `AZURE_CLIENT_SECRET`
   - `AZURE_TENANT_ID`
   - If all three are set, it uses Service Principal authentication

2. **Managed Identity** (if running on Azure)
   - Azure VM with Managed Identity enabled
   - Azure App Service with Managed Identity
   - Azure Functions with Managed Identity

3. **Azure CLI** (`az login`)
   - Most common for local development
   - Automatically detected if you've run `az login`

4. **Azure PowerShell**
   - If you're logged in via PowerShell

5. **Azure Developer CLI** (`azd`)
   - If using Azure Developer CLI

6. **Visual Studio Code**
   - If logged in via VS Code Azure extension

7. **Azure CLI (legacy)**
   - Older Azure CLI installations

## What You'll See

When you run the script, it will show you which credentials it detected:

### Scenario 1: Azure CLI (Most Common)
```
Checking Azure authentication...
✓ Will use Azure CLI credentials
  Account: Your Subscription Name
  Subscription ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### Scenario 2: Service Principal (Environment Variables)
```
Checking Azure authentication...
✓ Will use Service Principal credentials from environment variables
  Client ID: 12345678...
```

### Scenario 3: Automatic Detection
```
Checking Azure authentication...
✓ Will use DefaultAzureCredential - automatically detecting available credentials
  This will try: Azure CLI → Managed Identity → Environment Variables → etc.
```

## Examples

### Example 1: You have `az login` done
```bash
# You've already run: az login
python src/main.py
# → Automatically uses Azure CLI credentials
```

### Example 2: You have Service Principal in environment
```bash
export AZURE_CLIENT_ID="your-id"
export AZURE_CLIENT_SECRET="your-secret"
export AZURE_TENANT_ID="your-tenant"
python src/main.py
# → Automatically uses Service Principal (takes priority over Azure CLI)
```

### Example 3: Running on Azure VM with Managed Identity
```bash
python src/main.py
# → Automatically uses Managed Identity
```

### Example 4: Multiple methods available
```bash
# You have both az login AND environment variables set
export AZURE_CLIENT_ID="your-id"
export AZURE_CLIENT_SECRET="your-secret"
export AZURE_TENANT_ID="your-tenant"
# And you're also logged in via: az login

python src/main.py
# → Uses Service Principal (environment variables take priority)
```

## No Configuration Needed!

You don't need to:
- ❌ Specify which method to use
- ❌ Configure credentials in code
- ❌ Set up special authentication

Just:
- ✅ Have at least one authentication method available
- ✅ Run the script
- ✅ It automatically picks the right one!

## Priority Order

If multiple methods are available, it uses this priority:

1. **Environment Variables** (highest priority)
2. Managed Identity
3. Azure CLI
4. Azure PowerShell
5. Azure Developer CLI
6. Visual Studio Code
7. Azure CLI (legacy)

## Troubleshooting

### "No credentials found"
- Make sure at least one authentication method is available
- For local: Run `az login`
- For service principal: Set environment variables
- For Azure: Ensure Managed Identity is enabled

### "Wrong subscription"
- Check which account is active: `az account show`
- Switch subscription: `az account set --subscription "id"`
- Or unset environment variables if you want to use Azure CLI instead

## Summary

✅ **Fully automatic** - no configuration needed  
✅ **Tries multiple methods** - finds what's available  
✅ **Shows what it's using** - transparent about credentials  
✅ **Priority-based** - uses the most appropriate method  

Just run the script and it will figure out the credentials automatically!

