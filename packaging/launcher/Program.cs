using System.Diagnostics;
using System.Net.Http;

var root = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
var appRoot = Path.Combine(root, "app");
var runtimeRoot = Path.Combine(root, "runtime");
var logsRoot = Path.Combine(runtimeRoot, "logs");
var dataRoot = Path.Combine(runtimeRoot, "data");
var artifactsRoot = Path.Combine(dataRoot, "artifacts");
Directory.CreateDirectory(logsRoot);
Directory.CreateDirectory(dataRoot);
Directory.CreateDirectory(artifactsRoot);

var nodeExe = Path.Combine(runtimeRoot, "node", "node.exe");
var pythonExe = Path.Combine(runtimeRoot, "python", "python.exe");
var webRoot = Path.Combine(appRoot, "web");
var webServer = Path.Combine(webRoot, "apps", "web", "server.js");
var apiRoot = appRoot;
var uiRunnerDir = Path.Combine(appRoot, "workers", "ui-runner");
var configPath = Path.Combine(runtimeRoot, "config.env");

Console.Title = "AI Test Platform";
Console.OutputEncoding = System.Text.Encoding.UTF8;
Console.WriteLine("AI Test Platform portable launcher");
Console.WriteLine($"Root: {root}");

RequireFile(nodeExe, "Node runtime not found");
RequireFile(pythonExe, "Python runtime not found");
RequireFile(webServer, "Next.js standalone server not found");
RequireDirectory(Path.Combine(appRoot, "services", "ai-service"), "Backend service not found");

var config = LoadConfig(configPath);
var apiPort = GetValue(config, "AI_TEST_API_PORT", "8000");
var webPort = GetValue(config, "AI_TEST_WEB_PORT", "3000");
var apiUrl = $"http://127.0.0.1:{apiPort}";
var webUrl = $"http://127.0.0.1:{webPort}";

var apiEnv = new Dictionary<string, string?>
{
    ["AI_SERVICE_HOST"] = "127.0.0.1",
    ["AI_SERVICE_PORT"] = apiPort,
    ["AI_SERVICE_STORAGE_DIR"] = dataRoot,
    ["AI_SERVICE_ARTIFACTS_DIR"] = artifactsRoot,
    ["AI_SERVICE_DB_PATH"] = Path.Combine(dataRoot, "platform.db"),
    ["AI_SERVICE_DATABASE_URL"] = "",
    ["AI_SERVICE_REDIS_ENABLED"] = "false",
    ["AI_SERVICE_VECTOR_ENABLED"] = "false",
    ["AI_SERVICE_NODE_BIN"] = nodeExe,
    ["AI_SERVICE_UI_RUNNER_DIR"] = uiRunnerDir,
    ["AI_SERVICE_CORS_ALLOW_ORIGINS"] = $"{webUrl},http://localhost:{webPort},http://127.0.0.1:{webPort}",
    ["AI_SERVICE_MODEL_PROVIDER"] = GetValue(config, "AI_SERVICE_MODEL_PROVIDER", "openai-compatible"),
    ["AI_SERVICE_MODEL_BASE_URL"] = GetValue(config, "AI_SERVICE_MODEL_BASE_URL", "http://127.0.0.1:8317/v1"),
    ["AI_SERVICE_MODEL_NAME"] = GetValue(config, "AI_SERVICE_MODEL_NAME", "gpt-5.4-mini"),
    ["AI_SERVICE_MODEL_API_KEY"] = GetValue(config, "AI_SERVICE_MODEL_API_KEY", ""),
    ["AI_SERVICE_AUTH_SECRET"] = GetValue(config, "AI_SERVICE_AUTH_SECRET", "portable-dev-secret-change-me"),
    ["AI_SERVICE_DEFAULT_ADMIN_USERNAME"] = GetValue(config, "AI_SERVICE_DEFAULT_ADMIN_USERNAME", "admin"),
    ["AI_SERVICE_DEFAULT_ADMIN_PASSWORD"] = GetValue(config, "AI_SERVICE_DEFAULT_ADMIN_PASSWORD", "123456"),
    ["AI_SERVICE_DEFAULT_ADMIN_NAME"] = GetValue(config, "AI_SERVICE_DEFAULT_ADMIN_NAME", "超级管理员"),
    ["PLAYWRIGHT_BROWSERS_PATH"] = Path.Combine(runtimeRoot, "ms-playwright"),
};

var webEnv = new Dictionary<string, string?>
{
    ["NODE_ENV"] = "production",
    ["PORT"] = webPort,
    ["HOSTNAME"] = "127.0.0.1",
    ["PLATFORM_API_URL"] = apiUrl,
    ["NEXT_PUBLIC_PLATFORM_API_URL"] = webUrl,
    ["AUTH_COOKIE_MAX_AGE_SECONDS"] = "43200",
};

var processes = new List<Process>();
Console.CancelKeyPress += (_, eventArgs) =>
{
    eventArgs.Cancel = true;
    StopAll(processes);
    Environment.Exit(0);
};
AppDomain.CurrentDomain.ProcessExit += (_, _) => StopAll(processes);

try
{
    Console.WriteLine("Starting backend service...");
    processes.Add(StartProcess(
        pythonExe,
        "-m uvicorn app.main:app --app-dir services/ai-service --host 127.0.0.1 --port " + apiPort,
        apiRoot,
        apiEnv,
        Path.Combine(logsRoot, "api.log")));

    WaitForHttp(apiUrl + "/health", "backend");

    Console.WriteLine("Starting web service...");
    processes.Add(StartProcess(
        nodeExe,
        "apps/web/server.js",
        webRoot,
        webEnv,
        Path.Combine(logsRoot, "web.log")));

    WaitForHttp(webUrl, "web");

    Console.WriteLine();
    Console.WriteLine("AI Test Platform is running:");
    Console.WriteLine(webUrl);
    Console.WriteLine();
    Console.WriteLine("Close this window or press Ctrl+C to stop all services.");
    OpenBrowser(webUrl);

    while (processes.Any(p => !p.HasExited))
    {
        Thread.Sleep(1000);
    }
}
finally
{
    StopAll(processes);
}

static Process StartProcess(
    string fileName,
    string arguments,
    string workingDirectory,
    Dictionary<string, string?> environment,
    string logPath)
{
    var startInfo = new ProcessStartInfo
    {
        FileName = fileName,
        Arguments = arguments,
        WorkingDirectory = workingDirectory,
        UseShellExecute = false,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
        CreateNoWindow = true,
    };

    foreach (var item in environment)
    {
        startInfo.Environment[item.Key] = item.Value ?? "";
    }

    var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
    var logLock = new object();
    process.OutputDataReceived += (_, e) => WriteLog(logPath, e.Data, logLock);
    process.ErrorDataReceived += (_, e) => WriteLog(logPath, e.Data, logLock);
    if (!process.Start())
    {
        throw new InvalidOperationException($"Failed to start {fileName}");
    }
    process.BeginOutputReadLine();
    process.BeginErrorReadLine();
    return process;
}

static void WriteLog(string logPath, string? line, object logLock)
{
    if (line is null)
    {
        return;
    }
    lock (logLock)
    {
        File.AppendAllText(logPath, $"[{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}] {line}{Environment.NewLine}");
    }
}

static void WaitForHttp(string url, string label)
{
    using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
    var deadline = DateTimeOffset.Now.AddSeconds(90);
    while (DateTimeOffset.Now < deadline)
    {
        try
        {
            using var response = client.GetAsync(url).GetAwaiter().GetResult();
            if ((int)response.StatusCode < 500)
            {
                Console.WriteLine($"{label} is ready.");
                return;
            }
        }
        catch
        {
            // Service is still booting.
        }
        Thread.Sleep(1000);
    }
    throw new TimeoutException($"{label} did not become ready: {url}");
}

static void StopAll(List<Process> processes)
{
    foreach (var process in processes)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
            // Best-effort shutdown.
        }
    }
}

static void OpenBrowser(string url)
{
    try
    {
        Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });
    }
    catch
    {
        Console.WriteLine($"Open this URL manually: {url}");
    }
}

static Dictionary<string, string> LoadConfig(string path)
{
    var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    if (!File.Exists(path))
    {
        File.WriteAllLines(path, new[]
        {
            "# AI Test Platform portable configuration",
            "AI_TEST_API_PORT=8000",
            "AI_TEST_WEB_PORT=3000",
            "AI_SERVICE_MODEL_PROVIDER=openai-compatible",
            "AI_SERVICE_MODEL_BASE_URL=http://127.0.0.1:8317/v1",
            "AI_SERVICE_MODEL_NAME=gpt-5.4-mini",
            "AI_SERVICE_MODEL_API_KEY=",
            "AI_SERVICE_DEFAULT_ADMIN_USERNAME=admin",
            "AI_SERVICE_DEFAULT_ADMIN_PASSWORD=123456",
        });
    }

    foreach (var rawLine in File.ReadAllLines(path))
    {
        var line = rawLine.Trim();
        if (line.Length == 0 || line.StartsWith("#"))
        {
            continue;
        }
        var index = line.IndexOf('=');
        if (index <= 0)
        {
            continue;
        }
        values[line[..index].Trim()] = line[(index + 1)..].Trim();
    }
    return values;
}

static string GetValue(Dictionary<string, string> values, string key, string fallback)
{
    return values.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value)
        ? value.Trim()
        : fallback;
}

static void RequireFile(string path, string message)
{
    if (!File.Exists(path))
    {
        throw new FileNotFoundException(message, path);
    }
}

static void RequireDirectory(string path, string message)
{
    if (!Directory.Exists(path))
    {
        throw new DirectoryNotFoundException($"{message}: {path}");
    }
}
