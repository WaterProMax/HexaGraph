/** Text and code extensions a bot's library accepts. Keep in sync with backend `app/bots/files.py`. */
export const ALLOWED_EXTENSIONS = [
  "txt", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "toml", "ini", "log",
  "sql", "html", "css", "xml",
  "py", "ts", "tsx", "js", "jsx", "java", "go", "rs", "c", "cc", "cpp", "h", "hpp",
  "rb", "php", "sh", "swift", "kt",
] as const;

export const FILE_ACCEPT = ALLOWED_EXTENSIONS.map((ext) => `.${ext}`).join(",");

/** Reject absurdly large picks before reading them; the real cap is the bot's character budget. */
export const MAX_FILE_BYTES = 2 * 1024 * 1024;

export function isAllowedFile(name: string): boolean {
  const dot = name.lastIndexOf(".");
  if (dot < 0) return false;
  const ext = name.slice(dot + 1).toLowerCase();
  return (ALLOWED_EXTENSIONS as readonly string[]).includes(ext);
}

export function formatChars(value: number): string {
  return value.toLocaleString("en-US");
}

/** `File.text()` is missing in some environments (older jsdom); fall back to FileReader. */
export function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("读取文件失败"));
    reader.readAsText(file);
  });
}
