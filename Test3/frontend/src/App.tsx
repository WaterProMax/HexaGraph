import { Layout, Menu, Tag } from "antd";
import {
  ApartmentOutlined,
  AppstoreOutlined,
  DesktopOutlined,
  FolderOpenOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Link, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
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
import Workstation from "./pages/Workstation";

export default function App() {
  const loc = useLocation();
  const selectedKey = loc.pathname.startsWith("/projects")
    ? "p"
    : loc.pathname.startsWith("/settings")
    ? "s"
    : loc.pathname.startsWith("/runs")
    ? "r"
    : "w";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Sider width={210} theme="dark" style={{ borderRight: "1px solid #1f1f1f" }}>
        <div
          style={{
            height: 52,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 16px",
            color: "#fff",
            fontWeight: 700,
            fontSize: 15,
            borderBottom: "1px solid rgba(255,255,255,0.1)",
          }}
        >
          <span>HexaGraph</span>
          <Tag color="blue" style={{ margin: 0, fontSize: 10 }}>
            Test3
          </Tag>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          defaultOpenKeys={["proj", "ctrl"]}
          items={[
            {
              key: "proj",
              label: "Project Center",
              icon: <AppstoreOutlined />,
              children: [
                {
                  key: "w",
                  icon: <DesktopOutlined />,
                  label: <Link to="/workstation">Workstation</Link>,
                },
                {
                  key: "p",
                  icon: <FolderOpenOutlined />,
                  label: <Link to="/projects">Projects Registry</Link>,
                },
              ],
            },
            {
              key: "ctrl",
              label: "Control & Settings",
              icon: <ApartmentOutlined />,
              children: [
                {
                  key: "s",
                  icon: <SettingOutlined />,
                  label: <Link to="/settings">Models & Slots</Link>,
                },
              ],
            },
          ]}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Content style={{ minHeight: "100vh", background: "#f0f2f5" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/workstation" replace />} />
            <Route path="/workstation" element={<Workstation />} />
            <Route path="/workstation/:id" element={<Workstation />} />
            <Route
              path="/projects"
              element={
                <div style={{ padding: 16 }}>
                  <Projects />
                </div>
              }
            />
            <Route
              path="/settings"
              element={
                <div style={{ padding: 16 }}>
                  <Settings />
                </div>
              }
            />
            <Route
              path="/runs/:id/*"
              element={
                <div style={{ padding: 16 }}>
                  <RunShell />
                </div>
              }
            />
            <Route path="*" element={<Navigate to="/workstation" replace />} />
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
          { key: "ws", label: <Link to={`/workstation/${id}`}>Workstation 视图</Link> },
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
