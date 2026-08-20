from __future__ import annotations

import threading
from collections.abc import Callable
from tkinter import filedialog, messagebox

from .github import GitHubReleaseClient, GitHubRepository
from .gitlink import GitLinkAttachmentClient, GitLinkCli, GitLinkRepository
from .release_center import ReleaseCenter
from .release_models import ReleaseKind, ReleasePlan
from .remote import RemoteResourceManager
from .remote_release_providers import GitHubReleaseProvider, GitLinkReleaseProvider
from .updates import MODULE_ARCHIVE_RELEASE_TAG, UPDATE_RELEASE_TAG


class ReleaseCenterUiMixin:
    """Tk integration for the release center's application service boundary."""

    def _build_release_center_tab(self) -> None:
        self.release_center_tab.grid_columnconfigure(0, weight=1)
        self.release_center_tab.grid_rowconfigure(0, weight=1)
        self.release_center = ReleaseCenter(
            self.release_center_tab,
            service=self.release_service,
            remote_targets=self._release_center_remote_targets,
            execute_batch=self._execute_release_center_batch,
            pause_batch=self._pause_release_center_batch,
            default_inbox=self.workspace.output_dir / "updates",
            refresh_collection=self._refresh_release_center_collection,
            capture_baseline=self._capture_release_center_baseline,
            export_baseline=self._export_release_center_baseline,
            create_game_content_batch=self._create_current_game_content_batch,
            open_game_content_pipeline=self._open_game_content_release_pipeline,
        )
        self.release_center.grid(row=0, column=0, sticky="nsew")

    def _create_current_game_content_batch(self) -> ReleasePlan:
        """Snapshot the selected game's validated DLC/patch output into one batch."""
        profile = self.profile
        output_dir = self.workspace.output_dir / profile.game_id
        existing = self.release_service.find_reusable_game_content_batch(
            game_id=profile.game_id,
            release_tag=profile.release_tag,
            output_dir=output_dir,
        )
        if existing is not None:
            return existing
        files = self.workspace.publish_files(profile)
        catalog = next((path for path in files if path.name == "catalog.json"), None)
        if catalog is None:
            raise ValueError("当前游戏输出缺少 catalog.json；请重新构建后再加入上传队列。")
        attachments = [path for path in files if path != catalog]
        return self.release_service.create_game_content_batch(
            game_id=profile.game_id,
            release_tag=profile.release_tag,
            attachments=attachments,
            catalog=catalog,
            output_dir=output_dir,
            remote_targets=self._release_center_remote_targets(),
        )

    def _release_center_remote_targets(self) -> dict[str, dict[str, str]]:
        return {
            "gitlink": {
                "owner": self.settings.owner,
                "repository": self.settings.repository,
            },
            "github": {
                "owner": self.settings.github_owner,
                "repository": self.settings.github_repository,
            },
        }

    def _release_center_providers(self, batch_id: str, release_tag: str | None = None):
        plan = self.release_service.get(batch_id)

        def frozen_repository(provider: str) -> tuple[str, str]:
            target = plan.remote_targets.get(provider, {})
            owner = str(target.get("owner") or "").strip()
            repository = str(target.get("repository") or target.get("repo") or "").strip()
            if not owner or not repository:
                raise ValueError(
                    f"当前发布缺少 {provider} 的冻结目标仓库；为避免误发，请重新创建发布记录。"
                )
            return owner, repository

        def pause_requested() -> bool:
            return self.release_service.orchestrator.pause_requested(
                self.release_service.get(batch_id)
            )

        release_tag = release_tag or (
            str(plan.target.get("release_tag") or "hub")
            if plan.kind is not ReleaseKind.PROGRAM
            else UPDATE_RELEASE_TAG
        )
        github_owner, github_repository = frozen_repository("github")
        gitlink_owner, gitlink_repository = frozen_repository("gitlink")
        is_game_content = plan.kind is ReleaseKind.GAME_CONTENT
        repository_description = (
            f"SignRiver DLC / 补丁资源（{plan.target.get('game_id') or release_tag}）"
        )
        github = GitHubReleaseProvider(
            GitHubReleaseClient(
                GitHubRepository(github_owner, github_repository),
                self.settings.github_token,
            ),
            release_tag=release_tag,
            pause_requested=pause_requested,
            ensure_repository=is_game_content,
            repository_description=repository_description,
        )
        gitlink_target = GitLinkRepository(gitlink_owner, gitlink_repository)
        gitlink = GitLinkReleaseProvider(
            RemoteResourceManager(
                GitLinkAttachmentClient(self.settings.token or None),
                gitlink_target,
            ),
            release_tag=release_tag,
            release_name=f"SignRiver {release_tag}",
            pause_requested=pause_requested,
            repository_ensurer=(
                (lambda: GitLinkCli().ensure_repository(
                    gitlink_target, repository_description
                ))
                if is_game_content
                else None
            ),
        )
        return {"gitlink": gitlink, "github": github}

    def _refresh_release_center_collection(self, batch_id: str) -> None:
        inbox = self.release_center.inbox_entry.get().strip()
        module_inbox = self.release_center.module_inbox_entry.get().strip()
        try:
            plan = self.release_service.refresh_program_collection(
                batch_id, inbox, module_inbox
            )
            self.release_center._render(plan)
            self.release_center.refresh_history()
        except Exception as error:
            messagebox.showerror("刷新收件目录失败", str(error), parent=self)

    def _capture_release_center_baseline(self, batch_id: str) -> None:
        self.release_center.compare_button.configure(state="disabled", text="正在比较…")

        def restore_button() -> None:
            self.release_center.compare_button.configure(state="normal", text="验证并查看差异")

        def completed(plan: ReleasePlan) -> None:
            restore_button()
            self.release_center._render(plan)
            self.release_center._render_local_remote_comparison(plan)
            self.release_center.refresh_history()

        def failed(error: Exception) -> None:
            restore_button()
            self.release_center.comparison_summary.configure(
                text=f"云端比较失败：{error}"
            )

        def worker() -> None:
            try:
                providers = self._release_center_providers(batch_id, UPDATE_RELEASE_TAG)
                module_providers = self._release_center_providers(
                    batch_id, MODULE_ARCHIVE_RELEASE_TAG
                )
                plan = self.release_service.capture_remote_baseline(
                    batch_id, providers, module_providers
                )
                self._post_ui(lambda value=plan: completed(value))
            except Exception as error:
                self._post_ui(lambda value=error: failed(value))
        try:
            threading.Thread(
                target=worker, daemon=True, name="release-center-baseline"
            ).start()
        except RuntimeError as error:
            restore_button()
            messagebox.showerror("读取远端基线失败", str(error), parent=self)

    def _export_release_center_baseline(self, batch_id: str) -> None:
        plan = self.release_service.get(batch_id)
        target = str(plan.target.get("version") or plan.target.get("game_id") or "release")
        safe_target = "".join(char if char.isalnum() or char in ".-_" else "-" for char in target)
        destination = filedialog.asksaveasfilename(
            parent=self, title="导出远端基线", initialfile=f"signriver-remote-baseline-v{safe_target}.json",
            defaultextension=".json", filetypes=(("JSON", "*.json"), ("所有文件", "*.*")),
        )
        if not destination:
            return
        try:
            path = self.release_service.export_remote_baseline(batch_id, destination)
            messagebox.showinfo("导出完成", f"已导出：{path}", parent=self)
        except Exception as error:
            messagebox.showerror("导出基线失败", str(error), parent=self)

    def _execute_release_center_batch(
        self,
        batch_id: str,
        on_done: Callable[[ReleasePlan], None],
        on_error: Callable[[Exception], None],
    ) -> bool:
        if not self._begin_background_mutation(
            "release-center", "发布中心正在执行发布任务"
        ):
            return False

        def worker() -> None:
            try:
                plan = self.release_service.get(batch_id)
                providers = self._release_center_providers(batch_id)
                if plan.kind is ReleaseKind.PROGRAM:
                    module_providers = self._release_center_providers(batch_id, MODULE_ARCHIVE_RELEASE_TAG)
                    result = self.release_service.execute_program(batch_id, providers, module_providers)
                elif plan.kind is ReleaseKind.GAME_CONTENT:
                    result = self.release_service.execute_game_content(batch_id, providers)
                else:
                    result = self.release_service.execute_hub(batch_id, providers)
                self._post_ui(
                    lambda value=result: self._release_center_finished(value, on_done)
                )
            except Exception as error:
                self._post_ui(
                    lambda value=error: self._release_center_failed(value, on_error)
                )

        try:
            threading.Thread(target=worker, daemon=False, name="release-center").start()
        except RuntimeError:
            self._end_background_mutation("release-center")
            return False
        return True

    def _release_center_finished(
        self, plan: ReleasePlan, callback: Callable[[ReleasePlan], None]
    ) -> None:
        self._end_background_mutation("release-center")
        callback(plan)

    def _release_center_failed(
        self, error: Exception, callback: Callable[[Exception], None]
    ) -> None:
        self._end_background_mutation("release-center")
        callback(error)

    def _pause_release_center_batch(self, batch_id: str) -> None:
        try:
            self.release_service.request_pause(batch_id)
        except Exception as error:
            messagebox.showerror("无法暂停发布", str(error), parent=self)
