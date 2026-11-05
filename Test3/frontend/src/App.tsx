import { Layout, Menu } from "antd";
import { Link, Navigate, Route, Routes, useParams } from "react-router-dom";
import Overview from "./pages/Overview";
import Projects from "./pages/Projects";
import Discussion from "./pages/Discussion";
import Documents from "./pages/Documents";
import Todos from "./pages/Todos";
import Tasks from "./pages/Tasks";
import Timeline from "./pages/Timeline";
import Budget from "./pages/Budget";
import Settings from "./pages/Settings";
import Changes from "./pages/Changes";

export default function App() {
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Header style={{ color: "#fff" }}>Test3 多体工作流工作台</Layout.Header>
      <Layout>
        <Layout.Sider width={200} theme="light">
          <Menu
            items={[
              { key: "p", label: <Link to="/">项目</Link> },
              { key: "s", label: <Link to="/settings">设置</Link> },
            ]}
          />
        </Layout.Sider>
        <Layout.Content style={{ padding: 16 }}>
          <Routes>
            <Route path="/" element={<Projects />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/runs/:id/*" element={<RunShell />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}

function RunShell() {
  const { id } = useParams();
  return (
    <div>
      <Menu
        mode="horizontal"
        items={[
          { key: "o", label: <Link to={`/runs/${id}`}>总览</Link> },
          { key: "d", label: <Link to={`/runs/${id}/discussion`}>讨论</Link> },
          { key: "doc", label: <Link to={`/runs/${id}/docs`}>文档</Link> },
          { key: "t", label: <Link to={`/runs/${id}/todos`}>待办</Link> },
          { key: "g", label: <Link to={`/runs/${id}/tasks`}>任务图</Link> },
          { key: "tl", label: <Link to={`/runs/${id}/timeline`}>时间线</Link> },
          { key: "b", label: <Link to={`/runs/${id}/budget`}>预算</Link> },
          { key: "c", label: <Link to={`/runs/${id}/changes`}>变更与反馈</Link> },
        ]}
      />
      <Routes>
        <Route index element={<Overview />} />
        <Route path="discussion" element={<Discussion />} />
        <Route path="docs" element={<Documents />} />
        <Route path="todos" element={<Todos />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="timeline" element={<Timeline />} />
        <Route path="budget" element={<Budget />} />
        <Route path="changes" element={<Changes />} />
      </Routes>
    </div>
  );
}
