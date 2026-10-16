import { App, Modal, Setting } from "obsidian";
import type { Plan } from "../mirror/planner";

const CONFIRM_TEXT: Record<string, string> = {
  mass_delete: "Many files will be deleted from this device.",
  remote_empty: "The bridge reports an EMPTY vault. Everything on this device will be deleted.",
  first_sync_nonempty: "This vault is not empty. Existing files that are not on the bridge will be deleted.",
};

export function planSummary(plan: Plan): [string, number][] {
  const replace = plan.upserts.filter((u) => u.kind === "replace");
  return [
    ["Remote files", plan.manifest.entries.length],
    ["Local files", plan.localFileCount],
    ["Download", plan.upserts.length - replace.length],
    ["Replace", replace.length],
    ["  of which local edits", plan.upserts.filter((u) => u.localEdit).length],
    ["Delete", plan.deletes.length],
    ["  of which device-only", plan.deletes.filter((d) => d.reason === "local_only").length],
    ["Unchanged", plan.unchanged.length],
    ["Skipped (oversize)", plan.skippedOversize.length],
    ["Excluded remote (hidden/symlink/…)", Object.values(plan.manifest.excluded).reduce((a, b) => a + b, 0)],
  ];
}

/** Dry-run preview. Resolves true only when the user presses Apply with every confirmation ticked. */
export class PreviewModal extends Modal {
  private decided = false;

  constructor(
    app: App,
    private readonly plan: Plan,
    private readonly resolve: (apply: boolean) => void,
    private readonly readOnly = false,
  ) {
    super(app);
  }

  override onOpen(): void {
    const { contentEl } = this;
    this.setTitle(this.readOnly ? "Drive Mirror — dry run" : "Drive Mirror — preview");
    const table = contentEl.createEl("table", { cls: "drive-mirror-table" });
    for (const [label, n] of planSummary(this.plan)) {
      const tr = table.createEl("tr");
      tr.createEl("td", { text: label });
      tr.createEl("td", { text: n.toLocaleString() });
    }
    contentEl.createEl("p", {
      text: "Local edits, new local files and local renames are discarded. Nothing is ever uploaded.",
      cls: "mod-warning",
    });
    if (this.plan.deletes.length > 0) {
      const details = contentEl.createEl("details");
      details.createEl("summary", { text: `Files to delete (${this.plan.deletes.length})` });
      const ul = details.createEl("ul");
      for (const d of this.plan.deletes.slice(0, 200)) ul.createEl("li", { text: `${d.path} (${d.reason})` });
      if (this.plan.deletes.length > 200) ul.createEl("li", { text: "…" });
    }
    for (const w of this.plan.warnings.slice(0, 20)) contentEl.createEl("p", { text: w, cls: "mod-warning" });

    if (this.readOnly) {
      new Setting(contentEl).addButton((b) => b.setButtonText("Close").onClick(() => this.close()));
      return;
    }
    const ticks = new Map<string, boolean>(this.plan.confirmations.map((c) => [c, false]));
    let applyBtn: { setDisabled(d: boolean): unknown } | null = null;
    const refresh = () => applyBtn?.setDisabled([...ticks.values()].some((v) => !v));
    for (const c of this.plan.confirmations) {
      new Setting(contentEl)
        .setName(CONFIRM_TEXT[c] ?? c)
        .setDesc("Tick to confirm")
        .addToggle((t) =>
          t.onChange((v) => {
            ticks.set(c, v);
            refresh();
          }),
        );
    }
    new Setting(contentEl)
      .addButton((b) => b.setButtonText("Cancel").onClick(() => this.close()))
      .addButton((b) => {
        applyBtn = b;
        b.setButtonText("Apply")
          .setCta()
          .onClick(() => {
            this.decided = true;
            this.resolve(true);
            this.close();
          });
      });
    refresh();
  }

  override onClose(): void {
    this.contentEl.empty();
    if (!this.decided) this.resolve(false);
  }
}
