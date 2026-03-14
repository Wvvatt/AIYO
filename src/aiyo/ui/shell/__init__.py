"""Shell UI module for interactive terminal interface."""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Awaitable, Coroutine
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aiyo.bridge import AiyoSoul, StatusSnapshot
from aiyo.bridge.wire import (
    StatusUpdate, ContentPart, StepBegin, StepInterrupted,
)
from aiyo.ui.shell.console import console
from aiyo.ui.shell.echo import render_user_echo_text
from aiyo.ui.shell.prompt import (
    CustomPromptSession,
    PromptMode,
    UserInput,
    toast,
)
from aiyo.ui.shell.slash import registry as shell_slash_registry
from aiyo.ui.shell.slash import shell_mode_registry
from aiyo.ui.shell.visualize import visualize
from aiyo.utils.signals import install_sigint_handler
from aiyo.utils.subprocess_env import get_clean_env
from aiyo.utils.term import ensure_new_line, ensure_tty_sane
from aiyo.utils.slashcmd import SlashCommand, SlashCommandCall, parse_slash_command_call
from aiyo.utils.envvar import get_env_bool


class Shell:
    """Interactive shell UI for AIYO agent."""
    
    def __init__(self, soul: AiyoSoul, welcome_info: list["WelcomeInfoItem"] | None = None):
        self.soul = soul
        self._welcome_info = list(welcome_info or [])
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._prompt_session: CustomPromptSession | None = None
        self._available_slash_commands: dict[str, SlashCommand[Any]] = {
            **{cmd.name: cmd for cmd in soul.available_slash_commands},
            **{cmd.name: cmd for cmd in shell_slash_registry.list_commands()},
        }
    
    @property
    def available_slash_commands(self) -> dict[str, SlashCommand[Any]]:
        """Get all available slash commands."""
        return self._available_slash_commands
    
    @staticmethod
    def _should_exit_input(user_input: UserInput) -> bool:
        return user_input.command.strip() in {"exit", "quit", "/exit", "/quit"}
    
    @staticmethod
    def _agent_slash_command_call(user_input: UserInput) -> SlashCommandCall | None:
        if user_input.mode != PromptMode.AGENT:
            return None
        display_call = parse_slash_command_call(user_input.command)
        if display_call is None:
            return None
        resolved_call = parse_slash_command_call(user_input.resolved_command)
        if resolved_call is None or resolved_call.name != display_call.name:
            return display_call
        return resolved_call
    
    @staticmethod
    def _should_echo_agent_input(user_input: UserInput) -> bool:
        if user_input.mode != PromptMode.AGENT:
            return False
        if Shell._should_exit_input(user_input):
            return False
        return Shell._agent_slash_command_call(user_input) is None
    
    @staticmethod
    def _echo_agent_input(user_input: UserInput) -> None:
        console.print(render_user_echo_text(user_input.command))
    
    async def run(self, command: str | None = None) -> bool:
        """Run the shell interactively or execute a single command."""
        if command is not None:
            # Run single command and exit
            return await self.run_soul_command(command)
        
        # Start auto-update background task if not disabled
        if get_env_bool("AIYO_NO_AUTO_UPDATE"):
            pass  # Auto-update disabled
        else:
            # TODO: Add auto-update check
            pass
        
        _print_welcome_info(self.soul.name or "AIYO", self._welcome_info)
        
        async def _plan_mode_toggle() -> bool:
            return False  # Not implemented for AiyoSoul
        
        with CustomPromptSession(
            status_provider=lambda: self.soul.status,
            model_capabilities=self.soul.model_capabilities or set(),
            model_name=self.soul.model_name,
            thinking=self.soul.thinking or False,
            agent_mode_slash_commands=list(self._available_slash_commands.values()),
            shell_mode_slash_commands=shell_mode_registry.list_commands(),
            editor_command_provider=lambda: "",
            plan_mode_toggle_callback=_plan_mode_toggle,
        ) as prompt_session:
            self._prompt_session = prompt_session
            try:
                while True:
                    ensure_tty_sane()
                    try:
                        ensure_new_line()
                        user_input = await prompt_session.prompt()
                    except KeyboardInterrupt:
                        console.print("[grey50]Tip: press Ctrl-D or send 'exit' to quit[/grey50]")
                        continue
                    except EOFError:
                        console.print("Bye!")
                        break
                    
                    if not user_input:
                        continue
                    
                    if self._should_echo_agent_input(user_input):
                        self._echo_agent_input(user_input)
                    
                    if self._should_exit_input(user_input):
                        console.print("Bye!")
                        break
                    
                    if user_input.mode == PromptMode.SHELL:
                        await self._run_shell_command(user_input.command)
                        continue
                    
                    if slash_cmd_call := self._agent_slash_command_call(user_input):
                        await self._run_slash_command(slash_cmd_call)
                        continue
                    
                    await self.run_soul_command(user_input.content)
                    console.print()
            finally:
                self._prompt_session = None
                ensure_tty_sane()
        
        return True
    
    async def _run_shell_command(self, command: str) -> None:
        """Run a shell command in foreground."""
        if not command.strip():
            return
        
        # Check if it's an allowed slash command in shell mode
        if slash_cmd_call := parse_slash_command_call(command):
            if shell_mode_registry.find_command(slash_cmd_call.name):
                await self._run_slash_command(slash_cmd_call)
                return
            else:
                console.print(
                    f'[yellow]"/{slash_cmd_call.name}" is not available in shell mode. '
                    "Press Ctrl-X to switch to agent mode.[/yellow]"
                )
                return
        
        # Check if user is trying to use 'cd' command
        stripped_cmd = command.strip()
        split_cmd: list[str] | None = None
        try:
            split_cmd = shlex.split(stripped_cmd)
        except ValueError as exc:
            pass
        if split_cmd and len(split_cmd) == 2 and split_cmd[0] == "cd":
            console.print(
                "[yellow]Warning: Directory changes are not preserved across command executions."
                "[/yellow]"
            )
            return
        
        proc: asyncio.subprocess.Process | None = None
        
        def _handler():
            if proc:
                proc.terminate()
        
        loop = asyncio.get_running_loop()
        remove_sigint = install_sigint_handler(loop, _handler)
        try:
            proc = await asyncio.create_subprocess_shell(
                command, 
                env=get_clean_env()
            )
            await proc.wait()
        except Exception as e:
            console.print(f"[red]Failed to run shell command: {e}[/red]")
        finally:
            remove_sigint()
    
    async def _run_slash_command(self, command_call: SlashCommandCall) -> None:
        """Run a slash command."""
        from aiyo.ui.shell.slash import Reload
        
        if command_call.name not in self._available_slash_commands:
            console.print(
                f'[red]Unknown slash command "/{command_call.name}", '
                'type "/" for all available commands[/red]'
            )
            return
        
        command = shell_slash_registry.find_command(command_call.name)
        if command is None:
            # The input is a soul-level slash command call
            await self.run_soul_command(command_call.raw_input)
            return
        
        try:
            ret = command.func(self, command_call.args)
            if isinstance(ret, Awaitable):
                await ret
        except Reload:
            raise
        except (asyncio.CancelledError, KeyboardInterrupt):
            console.print("[red]Interrupted by user[/red]")
        except Exception as e:
            console.print(f"[red]Unknown error: {e}[/red]")
            raise
    
    async def run_soul_command(self, user_input: str | list[ContentPart]) -> bool:
        """Run the soul and handle any known exceptions."""
        cancel_event = asyncio.Event()
        
        def _handler():
            cancel_event.set()
        
        loop = asyncio.get_running_loop()
        remove_sigint = install_sigint_handler(loop, _handler)
        
        try:
            snap = self.soul.status
            
            # Convert ContentPart list to string if needed
            if isinstance(user_input, list):
                text = " ".join(p.content for p in user_input if hasattr(p, "content"))
            else:
                text = user_input
            
            # Use AiyoSoul's chat method
            response = await self.soul.chat(text)
            
            # Print response
            console.print(response)
            
            return True
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise
        finally:
            remove_sigint()
        return False


_KIMI_BLUE = "dodger_blue1"
_LOGO = f"""\
[{_KIMI_BLUE}]\
▐█▛█▛█▌
▐█████▌\
[{_KIMI_BLUE}]\
"""


@dataclass(slots=True)
class WelcomeInfoItem:
    class Level(Enum):
        INFO = "grey50"
        WARN = "yellow"
        ERROR = "red"
    
    name: str
    value: str
    level: Level = Level.INFO


def _print_welcome_info(name: str, info_items: list[WelcomeInfoItem]) -> None:
    """Print welcome information."""
    from rich.console import Group, RenderableType
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    
    head = Text.from_markup("Welcome to AIYO!")
    help_text = Text.from_markup("[grey50]Send /help for help information.[/grey50]")
    
    logo = Text.from_markup(_LOGO)
    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 1), expand=False)
    table.add_column(justify="left")
    table.add_column(justify="left")
    table.add_row(logo, Group(head, help_text))
    
    rows: list[RenderableType] = [table]
    
    if info_items:
        rows.append(Text(""))
    for item in info_items:
        rows.append(Text(f"{item.name}: {item.value}", style=item.level.value))
    
    console.print(
        Panel(
            Group(*rows),
            border_style=_KIMI_BLUE,
            expand=False,
            padding=(1, 2),
        )
    )


__all__ = ["Shell", "WelcomeInfoItem"]
