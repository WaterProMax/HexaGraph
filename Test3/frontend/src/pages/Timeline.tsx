import { Alert, List } from "antd";
import { useParams } from "react-router-dom";
import { useRunEvents } from "../hooks/useRunEvents";

export default function Timeline() {
  const { id } = useParams();
  const { events, connection, connectionError } = useRunEvents(id);
  return (
    <div className="stack" style={{ padding: 16 }}>
      {connection === "error" && (
        <Alert type="error" showIcon message={connectionError || "事件连接已断开"} style={{ marginBottom: 12 }} />
      )}
      <List dataSource={events} renderItem={(e: any) => <List.Item>{e.seq} {e.kind} {e.subject}</List.Item>} />
    </div>
  );
}
