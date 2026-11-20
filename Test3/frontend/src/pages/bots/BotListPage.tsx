export default function BotListPage({ mode = "list" }: { mode?: "list" | "create" | "edit" }) {
  return (
    <div className="page">
      <div className="page-head">
        <h1>Bot</h1>
        <p className="muted">Bot 工作台将在下一张卡接入（{mode}）。</p>
      </div>
    </div>
  );
}