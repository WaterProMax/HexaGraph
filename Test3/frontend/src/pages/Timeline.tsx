import { List } from "antd";
import { useParams } from "react-router-dom";
import { useRunEvents } from "../hooks/useRunEvents";

export default function Timeline() {
  const { id } = useParams();
  const events = useRunEvents(id);
  return <List dataSource={events} renderItem={(e: any) => <List.Item>{e.seq} {e.kind} {e.subject}</List.Item>} />;
}
