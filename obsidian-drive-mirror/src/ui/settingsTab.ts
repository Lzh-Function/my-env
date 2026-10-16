import { App, Notice, PluginSettingTab, Setting } from "obsidian";
import type DriveMirrorPlugin from "../main";

export class DriveMirrorSettingTab extends PluginSettingTab {
  constructor(
    app: App,
    private readonly plugin: DriveMirrorPlugin,
  ) {
    super(app, plugin);
  }

  override display(): void {
    const { containerEl } = this;
    const p = this.plugin;
    const s = p.settings;
    containerEl.empty();

    containerEl.createEl("p", {
      cls: "mod-warning",
      text: "Use only in a dedicated vault. Sync makes this vault identical to the bridge: local edits and device-only files are discarded. Nothing is ever uploaded.",
    });

    new Setting(containerEl).setHeading().setName("Connection");
    new Setting(containerEl)
      .setName("Provider")
      .setDesc("'mock' serves a built-in demo tree for desktop testing.")
      .addDropdown((d) =>
        d
          .addOptions({ bridge: "Self-hosted bridge (Tailscale)", mock: "Mock (testing)" })
          .setValue(s.provider)
          .onChange(async (v) => {
            s.provider = v as "bridge" | "mock";
            await p.saveSettings();
          }),
      );
    new Setting(containerEl)
      .setName("Bridge URL")
      .setDesc("e.g. https://<pc>.<tailnet>.ts.net:8443 (Tailscale Serve)")
      .addText((t) =>
        t
          .setPlaceholder("https://…ts.net:8443")
          .setValue(s.bridgeUrl)
          .onChange(async (v) => {
            s.bridgeUrl = v.trim();
            await p.saveSettings();
          }),
      );
    new Setting(containerEl)
      .setName("Bridge token")
      .setDesc(p.getToken() ? "Stored in Obsidian's secret storage on this device (not in the vault)." : "Paste the token printed by `drive-mirror-bridge init`.")
      .addText((t) => {
        t.inputEl.type = "password";
        t.setPlaceholder(p.getToken() ? "•••••• (set)" : "token").onChange((v) => {
          if (v.trim()) p.setToken(v.trim());
        });
      })
      .addButton((b) =>
        b.setButtonText("Forget").onClick(async () => {
          await p.forgetCredentials();
          this.display();
        }),
      );
    new Setting(containerEl).setName("Test connection").addButton((b) =>
      b.setButtonText("Test").onClick(async () => {
        try {
          const root = await p.buildProvider().verifyRoot();
          new Notice(`Bridge OK: root "${root.name}" (${root.rootId})`);
        } catch (e) {
          new Notice(`Bridge error: ${(e as Error).message}`);
        }
      }),
    );

    const pinned = p.state?.rootIdentity;
    new Setting(containerEl)
      .setName("Pinned root")
      .setDesc(pinned ? `${pinned.name} (${pinned.rootId})` : "Not pinned yet (pinned on first sync).")
      .addButton((b) =>
        b
          .setButtonText("Re-pin to current bridge root")
          .setDisabled(!pinned)
          .onClick(async () => {
            await p.repinRoot();
            this.display();
          }),
      );

    new Setting(containerEl).setHeading().setName("Sync");
    new Setting(containerEl).setName("Strict local hash verification").setDesc("Always on in v1: every local file is hashed on each sync.").addToggle((t) => t.setValue(true).setDisabled(true));
    new Setting(containerEl).setName("Automatic sync").setDesc("Off in v1. Sync manually while Obsidian is in the foreground.").addToggle((t) => t.setValue(false).setDisabled(true));
    new Setting(containerEl)
      .setName("Preview before every sync")
      .setDesc("Risky plans (mass delete, empty remote) always require a preview.")
      .addToggle((t) =>
        t.setValue(s.confirmBeforeApply).onChange(async (v) => {
          s.confirmBeforeApply = v;
          await p.saveSettings();
        }),
      );
    this.number(containerEl, "Max file size (MiB)", "Larger files are skipped (status PARTIAL).", "maxFileSizeMiB");
    this.number(containerEl, "Download chunk size (MiB)", "Large files are fetched in ranges of this size.", "chunkSizeMiB");
    this.number(containerEl, "Concurrent downloads", "1–3", "concurrency");
    this.number(containerEl, "Delete warning: count", "Ask before deleting at least this many files…", "deleteThresholdCount");
    this.number(containerEl, "Delete warning: percent", "…and at least this % of local files.", "deleteThresholdPercent");
    new Setting(containerEl)
      .setName("Allow non-empty first sync")
      .setDesc("Dangerous: lets the first sync delete existing files in this vault (after preview).")
      .addToggle((t) =>
        t.setValue(s.allowNonEmptyInit).onChange(async (v) => {
          s.allowNonEmptyInit = v;
          await p.saveSettings();
        }),
      );

    new Setting(containerEl).setHeading().setName("Status");
    const last = p.state?.history[0];
    new Setting(containerEl)
      .setName(`Last run: ${last ? `${last.status} at ${last.finishedAt}` : "never"}`)
      .setDesc(`Last complete sync: ${p.state?.lastCompleteSyncAt ?? "never"}`)
      .addButton((b) => b.setButtonText("Diagnostics").onClick(() => p.showReport()))
      .addButton((b) => b.setButtonText("Dry run").onClick(() => p.runSync(true)))
      .addButton((b) => b.setButtonText("Sync now").setCta().onClick(() => p.runSync(false)));
  }

  private number(el: HTMLElement, name: string, desc: string, key: "maxFileSizeMiB" | "chunkSizeMiB" | "concurrency" | "deleteThresholdCount" | "deleteThresholdPercent"): void {
    new Setting(el)
      .setName(name)
      .setDesc(desc)
      .addText((t) => {
        t.inputEl.type = "number";
        t.setValue(String(this.plugin.settings[key])).onChange(async (v) => {
          const n = Number(v);
          if (Number.isFinite(n) && n > 0) {
            this.plugin.settings[key] = n;
            await this.plugin.saveSettings();
          }
        });
      });
  }
}
