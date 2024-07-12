import click
import sys
import os
from dotenv import load_dotenv
from .query import execute_dravid_command
from ..prompts.claude_instructions import get_instruction_prompt
from .monitor import run_dev_server_with_monitoring
from ..metadata.initializer import initialize_project_metadata
from ..metadata.updater import update_metadata_with_dravid
from ..utils.api_utils import stream_claude_response
from ..utils.utils import print_error
from .ask_handler import handle_ask_command

def handle_query_command(query, image, debug):
    if not query and not sys.stdin.isatty():
        query = sys.stdin.read().strip()
    if not query:
        click.echo(
            "Please provide a query, use --meta-add to update metadata, --meta-init to initialize project metadata, or --ask for open-ended questions.")
        return
    instruction_prompt = get_instruction_prompt()
    execute_dravid_command(query, image, debug, instruction_prompt)

def dravid_cli_logic(query, image, debug, monitor_fix, meta_add, meta_init, ask, file):
    if monitor_fix:
        run_dev_server_with_monitoring()
    elif meta_add:
        update_metadata_with_dravid(meta_add, os.getcwd())
    elif meta_init:
        initialize_project_metadata(os.getcwd())
    elif ask or file:
        handle_ask_command(ask, file, debug)
    else:
        handle_query_command(query, image, debug)