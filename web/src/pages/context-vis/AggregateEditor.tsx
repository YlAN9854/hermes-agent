import { ArrowLeft, ArrowRight, GitMerge } from "lucide-react";
import type { ContextVisAggregate, ContextVisUnit } from "@/lib/api";
import { summariseSurvival } from "@/lib/context-vis";
import { Button } from "@nous-research/ui/ui/components/button";
import { Input } from "@nous-research/ui/ui/components/input";

export interface AggregateEditorProps {
  readonly nodes: readonly ContextVisAggregate[];
  readonly units: readonly ContextVisUnit[];
  readonly tier: number;
  readonly onChange: (nodes: ContextVisAggregate[]) => void;
}

export function AggregateEditor({
  nodes,
  units,
  tier,
  onChange,
}: AggregateEditorProps) {
  const unitTitle = Object.fromEntries(units.map((unit) => [unit.unit_id, unit.title]));
  const unitInfo = Object.fromEntries(units.map((unit) => [unit.unit_id, unit.salient_infos]));
  const update = (index: number, node: ContextVisAggregate): void => {
    onChange(nodes.map((current, position) => (
      position === index ? { ...node, origin: "user_edited" } : current
    )));
  };
  const move = (index: number, direction: -1 | 1): void => {
    const target = index + direction;
    if (target < 0 || target >= nodes.length) return;
    const next = nodes.map((node) => ({
      ...node,
      child_unit_ids: [...node.child_unit_ids],
      origin: "user_edited" as const,
    }));
    const sourceIds = next[index].child_unit_ids;
    const id = direction < 0 ? sourceIds.shift() : sourceIds.pop();
    if (!id || sourceIds.length === 0) return;
    if (direction < 0) next[target].child_unit_ids.push(id);
    else next[target].child_unit_ids.unshift(id);
    onChange(next);
  };
  const merge = (index: number): void => {
    if (index >= nodes.length - 1) return;
    const merged = {
      ...nodes[index],
      child_unit_ids: [
        ...nodes[index].child_unit_ids,
        ...nodes[index + 1].child_unit_ids,
      ],
      origin: "user_edited" as const,
    };
    onChange([...nodes.slice(0, index), merged, ...nodes.slice(index + 2)]);
  };
  const split = (index: number): void => {
    const node = nodes[index];
    if (node.child_unit_ids.length < 2) return;
    const cut = Math.ceil(node.child_unit_ids.length / 2);
    const left = {
      ...node,
      child_unit_ids: node.child_unit_ids.slice(0, cut),
      origin: "user_edited" as const,
    };
    const right = {
      ...node,
      node_id: `aggregate-user-${crypto.randomUUID()}`,
      title: `${node.title} 2`,
      child_unit_ids: node.child_unit_ids.slice(cut),
      origin: "user_edited" as const,
    };
    onChange([...nodes.slice(0, index), left, right, ...nodes.slice(index + 1)]);
  };

  return (
    <div className="space-y-2">
      {nodes.map((node, index) => {
        const infos = node.child_unit_ids.flatMap((id) => unitInfo[id] ?? []);
        const rollup = summariseSurvival(infos, tier);
        return (
          <div
            className="cv-panel-2 rounded-lg p-2"
            key={node.node_id}
            style={{ border: "1px solid var(--cv-border)" }}
          >
            <div className="flex items-center gap-1">
              <Input
                onChange={(event) => update(index, { ...node, title: event.target.value })}
                value={node.title}
              />
              <Button aria-label="Move boundary left" onClick={() => move(index, -1)} outlined size="sm">
                <ArrowLeft className="h-3 w-3" />
              </Button>
              <Button aria-label="Move boundary right" onClick={() => move(index, 1)} outlined size="sm">
                <ArrowRight className="h-3 w-3" />
              </Button>
              <Button onClick={() => split(index)} outlined size="sm">Split</Button>
              <Button aria-label="Merge with next aggregate" onClick={() => merge(index)} outlined size="sm">
                <GitMerge className="h-3 w-3" />
              </Button>
            </div>
            <p className="mt-1 text-xs" style={{ color: "var(--cv-text-dim)" }}>
              {node.child_unit_ids.map((id) => unitTitle[id] ?? id).join(" · ")}
            </p>
            {rollup && rollup.reframed + rollup.absent > 0 && (
              <p className="mt-1 text-[11px] font-mono">
                <span className="cv-reframed">{rollup.reframed} reframed</span>
                {" · "}
                <span className="cv-absent">{rollup.absent} gone</span>
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
