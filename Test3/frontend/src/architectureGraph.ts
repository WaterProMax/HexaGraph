type DesignModule = {
  code: string;
  name: string;
  responsibility?: string;
  sources?: string[];
  depends_on?: string[];
};

export type DesignInterface = {
  code: string;
  provider: string;
  consumers?: string[];
};

export type PlannedTask = {
  code: string;
  title: string;
  module: string;
  depends_on?: string[];
  points?: number;
  role?: string;
  kind?: string;
  sources?: string[];
  outputs?: string[];
  write_set?: string[];
  acceptance?: Array<{ cmd?: string[]; pass_criteria?: string }>;
};

export type ArchitectureDesign = { modules?: DesignModule[]; interfaces?: DesignInterface[] };
export type ArchitecturePlan = { tasks?: PlannedTask[] };

export type ArchitectureModule = DesignModule & {
  tasks: PlannedTask[];
  interfaces: DesignInterface[];
};

export type ArchitectureConnection = {
  id: string;
  source: string;
  target: string;
  interfaces: string[];
};

/** One cross-module task dependency direction, merged over the tasks that share it. */
export type ArchitectureTaskLink = {
  id: string;
  /** Module of the dependent task (edge goes from here to the dependency's module). */
  source: string;
  /** Module of the dependency task. */
  target: string;
  pairs: Array<{ task: string; dep: string }>;
};

/** Use the design as the authority for architecture, and the plan for module ownership. */
export function buildArchitectureGraph(design?: ArchitectureDesign, plan?: ArchitecturePlan): {
  modules: ArchitectureModule[];
  connections: ArchitectureConnection[];
  taskLinks: ArchitectureTaskLink[];
} {
  const modules = new Map<string, ArchitectureModule>();
  for (const module of design?.modules ?? []) {
    if (module.code && !modules.has(module.code)) {
      modules.set(module.code, { ...module, tasks: [], interfaces: [] });
    }
  }
  for (const task of plan?.tasks ?? []) modules.get(task.module)?.tasks.push(task);

  const connections = new Map<string, ArchitectureConnection>();
  function connect(source: string, target: string, contract?: string) {
    if (source === target || !modules.has(source) || !modules.has(target)) return;
    const id = JSON.stringify([source, target]);
    const connection = connections.get(id) ?? { id, source, target, interfaces: [] };
    if (contract && !connection.interfaces.includes(contract)) connection.interfaces.push(contract);
    connections.set(id, connection);
  }
  for (const module of modules.values()) {
    for (const dependency of module.depends_on ?? []) connect(module.code, dependency);
  }
  for (const contract of design?.interfaces ?? []) {
    const owners = new Set([contract.provider, ...(contract.consumers ?? [])]);
    for (const code of owners) modules.get(code)?.interfaces.push(contract);
    for (const consumer of contract.consumers ?? []) connect(consumer, contract.provider, contract.code);
  }

  // Cross-module task dependencies: one merged link per module pair, pairs keep task codes.
  // Ids are namespaced so they never collide with the module connection ids above.
  const taskModule = new Map<string, string>();
  for (const task of plan?.tasks ?? []) if (task.code) taskModule.set(task.code, task.module);
  const taskLinks = new Map<string, ArchitectureTaskLink>();
  for (const task of plan?.tasks ?? []) {
    const source = task.module;
    for (const dep of task.depends_on ?? []) {
      const target = taskModule.get(dep);
      if (!target || !modules.has(source) || !modules.has(target) || source === target) continue;
      const id = `t:${JSON.stringify([source, target])}`;
      const link = taskLinks.get(id) ?? { id, source, target, pairs: [] };
      if (!link.pairs.some((pair) => pair.task === task.code && pair.dep === dep)) {
        link.pairs.push({ task: task.code, dep });
      }
      taskLinks.set(id, link);
    }
  }

  return { modules: [...modules.values()], connections: [...connections.values()], taskLinks: [...taskLinks.values()] };
}
