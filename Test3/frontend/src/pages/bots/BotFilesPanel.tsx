import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { CloseOutlined, PlusOutlined } from "@ant-design/icons";
import { api } from "../../api/client";
import type { BotFileLibrary } from "../../api/types";
import {
  FILE_ACCEPT,
  MAX_FILE_BYTES,
  formatChars,
  isAllowedFile,
  readFileText,
} from "../../lib/botFiles";

type Props = { botId: string; disabled?: boolean };

/** 聊天输入框左侧的「+」：上传文本资料，保存在这个 Bot 名下，之后每次对话都会参考。 */
export function BotFilesPanel({ botId, disabled = false }: Props) {
  const [open, setOpen] = useState(false);
  const [library, setLibrary] = useState<BotFileLibrary | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setOpen(false);
    setLibrary(null);
    setError("");
  }, [botId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setLibrary(await api.botFiles(botId));
    } catch (err: any) {
      setError(err?.message || "加载资料文件失败");
    } finally {
      setLoading(false);
    }
  }, [botId]);

  useEffect(() => {
    if (open && library === null && !loading) void load();
    // load once per open; `library` stays null while the request is in flight or failed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node))
        setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const onPick = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0) return;
    setBusy(true);
    setError("");
    let current = "";
    try {
      for (const file of files) {
        current = file.name;
        if (!isAllowedFile(file.name))
          throw new Error("暂不支持该格式，只能上传文本和代码文件");
        if (file.size > MAX_FILE_BYTES)
          throw new Error("文件太大，超出资料上限");
        const content = await readFileText(file);
        const res = await api.uploadBotFile(botId, {
          filename: file.name,
          content,
        });
        setLibrary({
          items: res.items,
          used_chars: res.used_chars,
          budget_chars: res.budget_chars,
        });
      }
    } catch (err: any) {
      const message = err?.message || "上传失败";
      setError(current ? `「${current}」${message}` : message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (fileId: string) => {
    setError("");
    try {
      await api.deleteBotFile(botId, fileId);
      setLibrary((prev) => {
        if (!prev) return prev;
        const gone = prev.items.find((item) => item.file_id === fileId);
        return {
          ...prev,
          items: prev.items.filter((item) => item.file_id !== fileId),
          used_chars: prev.used_chars - (gone?.chars ?? 0),
        };
      });
    } catch (err: any) {
      setError(err?.message || "删除失败");
    }
  };

  const used = library?.used_chars ?? 0;
  const budget = library?.budget_chars ?? 0;
  const percent = budget > 0 ? Math.min(100, (used / budget) * 100) : 0;

  return (
    <div className="bot-files" ref={root}>
      <button
        type="button"
        className="bot-chat-plus"
        aria-label="资料文件"
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        <PlusOutlined />
      </button>
      {open && (
        <div
          className="bot-files-pop"
          role="dialog"
          aria-label="资料文件"
          data-testid="bot-files-panel"
        >
          <div className="bot-files-head">
            <strong>资料文件</strong>
            {library && (
              <span className="bot-files-usage" data-testid="bot-files-usage">
                已用 {formatChars(used)} / {formatChars(budget)} 字符
              </span>
            )}
          </div>
          <div
            className="bot-files-meter"
            role="progressbar"
            aria-label="资料用量"
            aria-valuemin={0}
            aria-valuemax={budget}
            aria-valuenow={used}
          >
            <i style={{ width: `${percent}%` }} />
          </div>
          <button
            type="button"
            className="bot-files-upload"
            disabled={busy}
            onClick={() => input.current?.click()}
          >
            {busy ? "上传中…" : "上传文件"}
          </button>
          <input
            ref={input}
            type="file"
            hidden
            multiple
            accept={FILE_ACCEPT}
            aria-label="选择文件"
            data-testid="bot-files-input"
            onChange={(event) => void onPick(event)}
          />
          {error && (
            <div className="bot-files-error" role="alert">
              {error}
            </div>
          )}
          {loading && <div className="bot-files-empty">正在加载…</div>}
          {library && library.items.length === 0 && (
            <div className="bot-files-empty">还没有资料文件</div>
          )}
          {library && library.items.length > 0 && (
            <ul className="bot-files-list" aria-label="已上传的文件">
              {library.items.map((item) => (
                <li key={item.file_id}>
                  <span className="bot-files-name" title={item.filename}>
                    {item.filename}
                  </span>
                  <span className="bot-files-size">
                    {formatChars(item.chars)}
                  </span>
                  <button
                    type="button"
                    className="bot-files-remove"
                    aria-label={`删除 ${item.filename}`}
                    onClick={() => void remove(item.file_id)}
                  >
                    <CloseOutlined />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default BotFilesPanel;
