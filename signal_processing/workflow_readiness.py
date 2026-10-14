"""
Whether one workflow chain can run as it stands, and which blocks stand in the way.

Architecture:
- Domain floor (Floor 5): one answer behind the status line, the outline on a
  faulty block and a refused Run -- they project `resolve_chain_readiness`, they do
  not each re-derive it.
- A chain is ready when its issue list is empty. The first issue is the headline
  (what the status line says and why Run refuses); the rest only add outlines.
- `find_selection` mirrors `ProjectSession.find_selection` and is passed in so this
  stays independent of `session/`. Without it a named selection is not looked up.

What does NOT belong here: wording that depends on where the answer is shown
("Not ready:" prefix, colours -- view_models/, gui/), which refusal code a Run
plan reports (orchestration/), which workflow is open (session/).
"""
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from core.workflow_graph import Workflow, resolve_workflow_chains
from signal_processing.workflow import resolve_block_errors, save_block_ids

ISSUE_MULTIPLE_INPUTS = "multiple_inputs"
ISSUE_INVALID_GRAPH = "invalid_graph"
ISSUE_INPUT_NOT_CHOSEN = "input_not_chosen"
ISSUE_SELECTION_MISSING = "selection_missing"
ISSUE_NO_SAVE_BLOCKS = "no_save_blocks"
ISSUE_NO_SAVE_CHANNELS = "no_save_channels"

__all__ = [
    "ReadinessIssue", "resolve_chain_readiness", "resolve_workflow_readiness",
    "ISSUE_MULTIPLE_INPUTS", "ISSUE_INVALID_GRAPH", "ISSUE_INPUT_NOT_CHOSEN",
    "ISSUE_SELECTION_MISSING", "ISSUE_NO_SAVE_BLOCKS", "ISSUE_NO_SAVE_CHANNELS",
]


@dataclass(frozen=True)
class ReadinessIssue:
    """One reason a chain cannot run. `block_ids` are the blocks it belongs to
    (empty: no particular block, it is only reported in the status line)."""
    code: str
    text: str
    block_ids: Tuple[str, ...] = ()


def resolve_chain_readiness(
    chain: Workflow,
    find_selection: Optional[Callable[[str], object]] = None,
) -> Tuple[ReadinessIssue, ...]:
    """Every reason `chain` cannot run, headline first; empty when it can."""
    everywhere = chain.block_ids
    inputs = [block.block_id for block in chain.blocks if block.is_input]
    if len(inputs) > 1:
        return (ReadinessIssue(
            ISSUE_MULTIPLE_INPUTS,
            f"Chains with multiple Input blocks ({len(inputs)}) are not supported yet.",
            everywhere,
        ),)

    try:
        block_errors = resolve_block_errors(chain)
    except ValueError as exc:
        # Graph-wide failure (no block, a cycle): it names blocks only
        # inside its text, so outline those, or the whole chain if none.
        text = str(exc)
        named = tuple(block_id for block_id in everywhere if f"'{block_id}'" in text)
        return (ReadinessIssue(ISSUE_INVALID_GRAPH, text, named or everywhere),)
    issues = [ReadinessIssue(ISSUE_INVALID_GRAPH, text, (block_id,))
              for block_id, text in block_errors.items()]

    if not inputs:
        # After the blocks' own errors, so those are what get outlined first.
        issues.append(ReadinessIssue(
            ISSUE_INVALID_GRAPH, "A workflow needs at least one input block.", everywhere,
        ))
        return tuple(issues)
    input_block = chain.block(inputs[0])
    spec = input_block.input
    if spec is None or (not spec.whole_pool and not spec.selection_name):
        issues.append(ReadinessIssue(
            ISSUE_INPUT_NOT_CHOSEN,
            "Pick what the input block runs over first ('Whole Data Pool', or a saved selection).",
            (input_block.block_id,),
        ))
    elif (not spec.whole_pool and find_selection is not None
          and find_selection(spec.selection_name) is None):
        issues.append(ReadinessIssue(
            ISSUE_SELECTION_MISSING,
            f"The input selection '{spec.selection_name}' no longer exists. "
            "Pick what the input block runs over first.",
            (input_block.block_id,),
        ))

    save_ids = save_block_ids(chain)
    if not save_ids:
        issues.append(ReadinessIssue(
            ISSUE_NO_SAVE_BLOCKS, "Tick 'Save this block's output' on at least one block first.",
        ))
    for block_id in save_ids:
        save = chain.block(block_id).save
        if not save.all_channels and not save.channel_identities:
            issues.append(ReadinessIssue(
                ISSUE_NO_SAVE_CHANNELS,
                f"Block '{block_id}' saves a result set but has no channels chosen.",
                (block_id,),
            ))
    return tuple(issues)


def resolve_workflow_readiness(
    workflow: Workflow,
    find_selection: Optional[Callable[[str], object]] = None,
) -> Tuple[Tuple[Workflow, Tuple[ReadinessIssue, ...]], ...]:
    """Each chain of `workflow` with its `resolve_chain_readiness`, in chain order.

    An empty workflow has no chains; it is reported as one, so it still says why it cannot run.
    """
    return tuple((chain, resolve_chain_readiness(chain, find_selection))
                 for chain in resolve_workflow_chains(workflow) or (workflow,))
