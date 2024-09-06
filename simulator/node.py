from typing import List, Dict, Tuple, Set, Sequence
from eth2spec.utils.ssz.ssz_typing import Bytes32, uint64
from dataclasses import dataclass
from utils import NodeId, SampleId, Root
from dascore import get_custody_columns
from enum import Enum


class NodeProfile:
    def __init__(self, honest, malicious, offline):
        self.honest = honest
        self.malicious = malicious
        self.offline = offline


@dataclass
class NodeRecord:
    node_id: NodeId
    children: List[NodeId]
    parents: List[NodeId]


@dataclass
class ScoreKeeper:
    """This class implements the score keeper data structure"""

    descendants_contacted: Dict[NodeId, Set[Tuple[NodeId, SampleId]]]
    descendants_replied: Dict[NodeId, Set[Tuple[NodeId, SampleId]]]


@dataclass
class RatedListDHT:
    """This class implements the rated list data structure"""

    sample_mapping: Dict[SampleId, Set[NodeId]]
    nodes: Dict[NodeId, NodeRecord]
    scores: Dict[Root, ScoreKeeper]


class Node:
    """This class implements a node in the network"""

    def __init__(self, id: NodeId):
        print(" starting a new node in the network")
        self.own_id = id
        self.dht = RatedListDHT({}, {}, {})

        self.dht.nodes[id] = NodeRecord(id, [], [])

        print(" started a node in the node with nodeId - %s", id)

    def compute_descendant_score(self, block_root: Root, node_id: NodeId) -> float:
        score_keeper = self.dht.scores[block_root]
        return (
            len(score_keeper.descendants_replied[node_id])
            / len(score_keeper.descendants_contacted[node_id])
            if len(score_keeper.descendants_contacted[node_id]) > 0
            else 0
        )

    def on_get_peers_response(self, node_id: NodeId, peers: Sequence[NodeId]):
        for peer_id in peers:
            child_node: NodeRecord = None

            if peer_id not in self.dht.nodes:
                child_node = NodeRecord(peer_id, [], [])
                self.dht.nodes[peer_id] = child_node

            self.dht.nodes[peer_id].parents.append(node_id)
            self.dht.nodes[node_id].children.append(peer_id)

        for child_id in self.dht.nodes[node_id].children:
            if child_id not in peers:
                # Node no longer has child peer, remove link
                self.dht.nodes[node_id].children.remove(child_id)
                self.dht.nodes[child_id].parents.remove(node_id)

                if len(self.dht.nodes[child_id].parents) == 0:
                    del self.dht.nodes[child_id]

    def compute_node_score(self, block_root: Root, node_id: NodeId) -> float:
        score = self.compute_descendant_score(block_root, node_id)

        cur_path_scores: Dict[NodeId, float] = {
            parent: score for parent in self.dht.nodes[node_id].parents
        }

        best_score = 0.0

        # traverse all paths of node_id by iterating through its parents and
        # grand parents. Note the best score when the iteration reaches root
        while cur_path_scores:
            new_path_scores: Dict[NodeId, float] = {}
            for node, score in cur_path_scores.items():
                for parent in self.dht.nodes[node].parents:
                    if parent == self.own_id:
                        best_score = max(best_score, score)
                    else:
                        par_score = self.compute_descendant_score(block_root, parent)
                        if (
                            parent not in new_path_scores
                            or new_path_scores[parent] < par_score
                        ):
                            new_path_scores[parent] = par_score

            cur_path_scores = new_path_scores

        return best_score

    # FIXME: the iteration is endless
    def on_request_score_update(
        self, block_root: Root, node_id: NodeId, sample_id: SampleId
    ):
        node_record = self.dht.nodes[node_id]

        if block_root not in self.dht.scores:
            self.dht.scores[block_root] = ScoreKeeper({}, {})

        score_keeper = self.dht.scores[block_root]

        cur_ancestors = set(node_record.parents)

        while cur_ancestors:
            new_ancestors = set()
            for ancestor in cur_ancestors:
                if ancestor not in score_keeper.descendants_contacted:
                    score_keeper.descendants_contacted[ancestor] = set()

                score_keeper.descendants_contacted[ancestor].add((node_id, sample_id))
                new_ancestors.update(self.dht.nodes[ancestor].parents)
            cur_ancestors = new_ancestors

    # FIXME: the iteration is endless
    def on_response_score_update(
        self, block_root: Root, node_id: NodeId, sample_id: SampleId
    ):
        node_record = self.dht.nodes[node_id]
        score_keeper = self.dht.scores[block_root]

        cur_ancestors = set(node_record.parents)

        while cur_ancestors:
            new_ancestors = set()
            for ancestor in cur_ancestors:
                if ancestor not in score_keeper.descendants_replied:
                    score_keeper.descendants_replied[ancestor] = set()

                score_keeper.descendants_replied[ancestor].add((node_id, sample_id))
                new_ancestors.update(self.dht.nodes[ancestor].parents)
            cur_ancestors = new_ancestors

    def add_samples_on_entry(self, node_id: NodeId):
        # TODO: support a variable custody count for nodes
        sample_ids = get_custody_columns(node_id)

        for id in sample_ids:
            if id not in self.dht.sample_mapping:
                self.dht.sample_mapping[id] = set()

            self.dht.sample_mapping[id].add(node_id)

    def remove_samples_on_exit(self, node_id: NodeId):
        # TODO: support a variable custody count for nodes
        sample_ids = get_custody_columns(node_id)

        for id in sample_ids:
            if id not in self.dht.sample_mapping:
                continue

            self.dht.sample_mapping[id].remove(node_id)

    def filter_nodes(self, block_root: Bytes32, sample_id: SampleId) -> List[NodeId]:
        scores = []
        filter_score = 0.9
        filtered_nodes = set()
        evicted_nodes = set()

        while len(filtered_nodes) == 0:
            for node_id in self.dht.sample_mapping[sample_id]:
                score = self.compute_node_score(block_root, node_id)
                scores.append((node_id, score))

                if score >= filter_score and node_id not in evicted_nodes:
                    filtered_nodes.update(node_id)
                elif score < filter_score:
                    evicted_nodes.update(self.dht.nodes[node_id])
                    evicted_nodes.update(self.dht.nodes[node_id].children)

            # if no nodes are filtered then reset the filter score to avg - 0.1. this will guarantee atleast one node.
            filter_score = sum([score for _, score in scores]) / len(scores) - 0.1

        return filtered_nodes

    def request_sample(
        self, node_id: NodeId, block_root: Root, samples: Sequence[SampleId]
    ):
        print("not implemented")

    def get_peers(self, node_id: NodeId):
        print("not implemented")
