from __future__ import annotations

from dataclasses import dataclass

from pine2ast.ast.base import ASTNode
from pine2ast.ast.walk import iter_child_nodes


@dataclass(frozen=True, slots=True)
class NodeIndex:
    nodes: tuple[ASTNode, ...]
    object_to_node_id: dict[int, str]
    parent_by_object_id: dict[int, ASTNode | None]

    @classmethod
    def build(cls, root: ASTNode) -> "NodeIndex":
        nodes: list[ASTNode] = []
        object_to_node_id: dict[int, str] = {}
        parent_by_object_id: dict[int, ASTNode | None] = {}

        def visit(node: ASTNode, parent: ASTNode | None) -> None:
            object_id = id(node)
            if object_id in object_to_node_id:
                raise ValueError(
                    f"AST node {node.kind} is shared by multiple parents; stable identity is ambiguous"
                )
            object_to_node_id[object_id] = f"n{len(nodes):08d}"
            parent_by_object_id[object_id] = parent
            nodes.append(node)
            for child in iter_child_nodes(node):
                visit(child, node)

        visit(root, None)
        return cls(tuple(nodes), object_to_node_id, parent_by_object_id)

    def id_for(self, node: ASTNode) -> str:
        try:
            return self.object_to_node_id[id(node)]
        except KeyError as exc:
            raise KeyError("node does not belong to this AST index") from exc

    def parent_for(self, node: ASTNode) -> ASTNode | None:
        if id(node) not in self.parent_by_object_id:
            raise KeyError("node does not belong to this AST index")
        return self.parent_by_object_id[id(node)]


__all__ = ["NodeIndex"]
