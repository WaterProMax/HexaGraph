import { useRef, useState } from "react";
import { Alert, Button } from "antd";
import { api } from "../../../api/client";

export const MAX_SUPPLEMENT_LENGTH = 2000;

export type SupplementComposerProps = {
  /** Session awaiting approval, used as the link target for the new session. */
  sessionId: string;
  actorBotId: string;
  /** Called after the new session is created so the caller can reload the view. */
  onSent: () => void;
};

function supplementErrorText(err: unknown): string {
  if (err && typeof err === "object" && "category" in err && err.category === "secret_in_body") {
    return "补充信息里看起来有密钥，请删除后重试";
  }
  const message = (err as { message?: unknown } | null)?.message;
  return typeof message === "string" && message.trim() ? message : "发送失败，请稍后重试";
}

/** Appends extra requirements from the pending-approval state and starts a new discussion. */
export function SupplementComposer({
  sessionId,
  actorBotId,
  onSent,
}: SupplementComposerProps) {
  const busyRef = useRef(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const trimmed = text.trim();

  const send = async () => {
    if (!trimmed || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await api.supplementDiscussion(sessionId, trimmed, actorBotId);
      setText("");
      onSent();
    } catch (err) {
      setError(supplementErrorText(err));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  return (
    <section className="disc-composer disc-supplement" aria-label="补充讨论信息">
      <form
        className="disc-composer-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label className="disc-composer-field" htmlFor="disc-supplement-input">
          <span className="disc-composer-label">补充信息</span>
          <textarea
            id="disc-supplement-input"
            className="disc-composer-input"
            aria-label="补充信息"
            rows={3}
            maxLength={MAX_SUPPLEMENT_LENGTH}
            value={text}
            disabled={busy}
            placeholder="补充缺失规则或验收标准，会开启一轮新讨论。"
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <div className="disc-composer-meta">
          <span className="disc-composer-count">
            {text.length} / {MAX_SUPPLEMENT_LENGTH}
          </span>
        </div>

        {error && (
          <Alert className="disc-composer-error" type="error" showIcon role="alert" message={error} />
        )}

        <div className="disc-composer-actions">
          <Button
            type="primary"
            htmlType="submit"
            className="disc-composer-start"
            loading={busy}
            disabled={busy || trimmed.length === 0}
          >
            发送补充
          </Button>
        </div>
      </form>
    </section>
  );
}

export default SupplementComposer;