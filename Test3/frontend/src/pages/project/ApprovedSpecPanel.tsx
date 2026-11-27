import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { DiscussionSession } from "../../api/types";
import { SpecDocument, discussionVersion, latestApproved } from "./discussion/SpecDocument";

const EMPTY_SESSIONS: DiscussionSession[] = [];

/**
 * Read-only "完整规格" panel for the project task view.
 *
 * Priority is honest: the latest approved discussion markdown (with history) is
 * the real requirement spec. The scripted gate path often has no discussion
 * package, so the panel falls back to the complete approved SPEC artifact
 * (`artifacts.spec`), listing every feature instead of the 3-row summary.
 * When neither exists it says so — it never invents a body.
 */

export type ApprovedSpecStatus =
  | { kind: "discussion"; version: number }
  | { kind: "artifact"; baseline?: string }
  | { kind: "none" };

type ArtifactState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "empty" }
  | { status: "error" }
  | { status: "ready"; spec: any; baseline?: string };

export type ApprovedSpecPanelProps = {
  /** Full discussion session list for the project (newest or oldest order both work). */
  sessions?: DiscussionSession[];
  /** Run whose approved SPEC artifact is the fallback source. */
  runId?: string;
  /** Reports which source is actually shown, for the context bar. */
  onStatusChange?: (status: ApprovedSpecStatus) => void;
};

function itemLabel(item: unknown): string {
  if (item == null) return "";
  if (typeof item === "string") return item;
  if (typeof item === "number" || typeof item === "boolean") return String(item);
  if (typeof item === "object") {
    const record = item as Record<string, unknown>;
    const title = [record.title, record.text, record.description, record.summary].find(
      (value) => typeof value === "string" && value.trim(),
    );
    const code = typeof record.code === "string" ? record.code.trim() : "";
    if (code && title) return `${code} ${String(title).trim()}`;
    if (title) return String(title).trim();
    if (code) return code;
    try {
      return JSON.stringify(item);
    } catch {
      return String(item);
    }
  }
  return String(item);
}

function SpecList({
  title,
  items,
  testid,
  emptyText,
}: {
  title: string;
  items: unknown[];
  testid: string;
  emptyText: string;
}) {
  return (
    <section className="approved-spec-section" data-testid={`${testid}-section`}>
      <h4>
        {title}
        <span className="hint"> {items.length}</span>
      </h4>
      {items.length === 0 ? (
        <p className="muted">{emptyText}</p>
      ) : (
        <ul>
          {items.map((item, index) => (
            <li key={`${testid}-${index}`} data-testid={testid}>
              {itemLabel(item)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function listOf(spec: any, key: string): unknown[] {
  return Array.isArray(spec?.[key]) ? spec[key] : [];
}

export function ApprovedSpecPanel({ sessions = EMPTY_SESSIONS, runId, onStatusChange }: ApprovedSpecPanelProps) {
  const approved = latestApproved(sessions);
  const approvedBody = approved?.decision_package?.body_md?.trim() ? approved : null;
  const [artifact, setArtifact] = useState<ArtifactState>({ status: "idle" });

  useEffect(() => {
    if (approvedBody) {
      setArtifact({ status: "idle" });
      return;
    }
    if (!runId) {
      setArtifact({ status: "empty" });
      return;
    }
    let cancelled = false;
    setArtifact({ status: "loading" });
    api
      .artifacts(runId)
      .then((artifacts: any) => {
        if (cancelled) return;
        const spec = artifacts?.spec;
        if (!spec) {
          setArtifact({ status: "empty" });
          return;
        }
        setArtifact({ status: "ready", spec, baseline: artifacts?.baseline_SPEC });
      })
      .catch(() => {
        if (!cancelled) setArtifact({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [runId, approvedBody]);

  useEffect(() => {
    if (approvedBody) {
      onStatusChange?.({ kind: "discussion", version: discussionVersion(approvedBody, sessions) });
      return;
    }
    if (artifact.status === "ready") {
      onStatusChange?.({ kind: "artifact", baseline: artifact.baseline });
      return;
    }
    if (artifact.status === "empty" || artifact.status === "error") {
      onStatusChange?.({ kind: "none" });
    }
  }, [approvedBody, artifact, sessions, onStatusChange]);

  const requirementText = approvedBody?.requirement_text?.trim() || "";

  return (
    <section
      className="glass-panel approved-spec"
      data-testid="approved-spec-panel"
      aria-labelledby="approved-spec-heading"
    >
      <div className="section-title approved-spec-head">
        <span id="approved-spec-heading">完整规格</span>
        <span className="hint">
          {approvedBody
            ? `第 ${discussionVersion(approvedBody, sessions)} 次讨论 · 已批准`
            : artifact.status === "ready"
              ? "已批准 SPEC 工件"
              : "只读"}
        </span>
      </div>

      {approvedBody ? (
        <div className="approved-spec-body" data-testid="approved-spec-discussion">
          {requirementText && (
            <p className="approved-spec-req" data-testid="approved-spec-requirement">
              <strong>原始需求</strong>
              <span>{requirementText}</span>
            </p>
          )}
          <p className="muted approved-spec-source">
            来自项目讨论的已批准规格正文（Markdown，只读；历史版本可切换）。
          </p>
          <SpecDocument sessions={sessions} className="approved-spec-document" />
        </div>
      ) : artifact.status === "loading" ? (
        <p className="muted" role="status">
          正在载入已批准规格…
        </p>
      ) : artifact.status === "ready" ? (
        <div className="approved-spec-body" data-testid="approved-spec-artifact">
          <p className="muted approved-spec-source">
            数据来自已批准 SPEC 工件
            {artifact.baseline ? ` · 基线 v${artifact.baseline}` : ""}
            （结构化工件，不是讨论 Markdown 正文）。
          </p>
          <SpecList
            title="功能"
            items={listOf(artifact.spec, "features")}
            testid="approved-spec-feature"
            emptyText="未列出功能。"
          />
          <SpecList
            title="场景"
            items={listOf(artifact.spec, "scenarios")}
            testid="approved-spec-scenario"
            emptyText="未列出场景。"
          />
          <SpecList
            title="非功能"
            items={listOf(artifact.spec, "nonfunc")}
            testid="approved-spec-nonfunc"
            emptyText="未列出非功能项。"
          />
          <SpecList
            title="范围外"
            items={listOf(artifact.spec, "out_of_scope")}
            testid="approved-spec-out-of-scope"
            emptyText="未声明范围外事项。"
          />
          <SpecList
            title="待定问题"
            items={listOf(artifact.spec, "open_questions")}
            testid="approved-spec-open-question"
            emptyText="没有待定问题。"
          />
        </div>
      ) : artifact.status === "error" ? (
        <p className="muted" role="alert" data-testid="approved-spec-error">
          暂时无法载入已批准规格。
        </p>
      ) : (
        <p className="muted" data-testid="approved-spec-empty">
          尚未生成已批准规格。
        </p>
      )}
    </section>
  );
}

export default ApprovedSpecPanel;