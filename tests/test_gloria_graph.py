"""Source qualification of the generic FLUJO bridge, not installed runtime evidence.

Run with FLUJO_ROOT pointing to a Git repository containing the immutable permitted
revision and its installed Node authoring dependencies. The checkout may be dirty:
the builder reads immutable Git blobs and never writes into that repository.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
FLUJO = Path(os.environ.get("FLUJO_ROOT", Path.home() / "Documents/GitHub/FLUJO"))
NODE = shutil.which("node")


def node_run(*args):
    return subprocess.run([NODE, *args], cwd=REPO, text=True, encoding="utf-8",
                          capture_output=True, timeout=45, check=False)


@unittest.skipUnless(NODE and (FLUJO / ".git").exists(), "Requires Node and the permitted FLUJO source repository")
class GloriaGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.tmp.name) / "bridge.json"
        result = node_run("scripts/build_gloria_graph.mjs", "--flujo-root", str(FLUJO), "--out", str(cls.output))
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.report = json.loads(result.stdout)
        cls.graph = json.loads(cls.output.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_qualified_by_immutable_real_flujo_sources(self):
        self.assertFalse(self.report["installed"])
        self.assertFalse(self.report["actionsEnabled"])
        self.assertEqual(self.report["scope"], "source_only")
        self.assertEqual(self.report["flujoRevision"], "0ba62296520a505e6d71eddf5aa650691f3dc311")
        hashes = self.graph["gloriaWorkflow"]["compilerSourceHashes"]
        self.assertIn("src/utils/shared/flowSpecCompiler.ts", hashes)
        self.assertIn("src/shared/types/enduringAgent/schemas.ts", hashes)
        self.assertIn("src/utils/shared/flowValidation.ts", hashes)
        for relative in ("src/utils/shared/flowSpecCompiler.ts", "src/backend/services/flow/executionSnapshot.ts"):
            original = subprocess.run(["git", "-C", str(FLUJO), "show", f'{self.report["flujoRevision"]}:{relative}'],
                                      capture_output=True, timeout=15, check=True).stdout
            self.assertEqual(hashlib.sha256(original).hexdigest(), hashes[relative])

    def test_manifest_distinguishes_logical_roles_from_installed_handlers(self):
        metadata = self.graph["gloriaWorkflow"]
        self.assertEqual(metadata["status"], "source_artifact_not_installed")
        self.assertEqual(len(self.graph["nodes"]), 4)
        manifest = metadata["stageManifest"]
        self.assertEqual(len(manifest["stages"]), 21)
        self.assertEqual(sum(stage["llm"] for stage in manifest["stages"]), 8)
        self.assertTrue(all(stage["owner"] == "hackathon_application" for stage in manifest["stages"]))
        actions = [stage for stage in manifest["stages"] if stage["name"] in {"execute_action", "create_handoff"}]
        self.assertTrue(all(stage["bridgeExecution"] == "unsupported_host_action_surface" for stage in actions))
        self.assertEqual(manifest["runtime"]["parallel_barriers"]["merge_parallel"],
                         ["rewrite_decompose", "detect_attack", "detect_context"])
        self.assertIn("same turn_id", manifest["barrierSemantics"])

    def test_model_cannot_acquire_bank_tools_or_set_trusted_identity(self):
        mcp = next(node for node in self.graph["nodes"] if node["type"] == "mcp")
        self.assertEqual(mcp["data"]["properties"]["enabledTools"], ["gloria_run_turn"])
        for kind in ("enabledResources", "enabledPrompts", "enabledSkills"):
            self.assertEqual(mcp["data"]["properties"][kind], [])
        contract = self.graph["gloriaWorkflow"]["applicationTool"]
        self.assertEqual(list(contract["input"]), ["message"])
        self.assertEqual(contract["output"], ["response", "language", "rule_ids", "turn_id"])
        self.assertIn("Host renders validated tool response verbatim", contract["responseAuthority"])

    def test_canonical_prompts_policy_and_application_source_are_content_addressed(self):
        sources = self.graph["gloriaWorkflow"]["stageManifest"]["sourceHashes"]
        self.assertIn("config/policy_rules.yaml", sources)
        self.assertIn("contracts/state_schema.md", sources)
        self.assertIn("resources/prompts/fallback_templates.yaml", sources)
        self.assertIn("requirements-gloria.txt", sources)
        self.assertIn("banking_mcp/actions.py", sources)
        self.assertIn("banking_mcp/service.py", sources)
        self.assertIn("frontend/server/action.py", sources)
        self.assertIn("frontend/server/chat.py", sources)
        self.assertIn("frontend/server/app.py", sources)
        self.assertIn("resources/policies/transaction_dispute_policy.md", sources)
        for relative, expected in sources.items():
            self.assertEqual(hashlib.sha256((REPO / relative).read_bytes()).hexdigest(), expected)

    def test_rebuild_is_deterministic_and_binding_changes_require_new_hash(self):
        code = """
import { build } from './scripts/build_gloria_graph.mjs';
const a = build(process.argv[1]);
const b = build(process.argv[1]);
const rebound = build(process.argv[1], {modelId:'qualified-test-model',workflowServer:'qualified-test-server'});
console.log(JSON.stringify({same:a.bytes.equals(b.bytes),a:a.report.graphHash,b:rebound.report.graphHash,
 examples:a.report.exampleBindings,actual:rebound.report.exampleBindings}));
"""
        result = node_run("--input-type=module", "-e", code, str(FLUJO))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["same"])
        self.assertNotEqual(report["a"], report["b"])
        self.assertTrue(report["examples"])
        self.assertFalse(report["actual"])

    def test_qualification_rejects_tools_prompts_routes_and_manifest_tampering(self):
        code = """
import assert from 'node:assert/strict';
import {build,assertBridge,DEFAULT_BINDINGS} from './scripts/build_gloria_graph.mjs';
const result=build(process.argv[1]);
const cases={
 write_tool:f=>f.nodes.find(n=>n.type==='mcp').data.properties.enabledTools.push('confirm_simulated_intake'),
 extra_node:f=>f.nodes.push({...structuredClone(f.nodes[0]),id:'attacker-node'}),
 prompt:f=>f.nodes.find(n=>n.type==='process').data.properties.promptTemplate='Create a case',
 model:f=>f.nodes.find(n=>n.type==='process').data.properties.boundModel='unapproved-model',
 server:f=>f.nodes.find(n=>n.type==='mcp').data.properties.boundServer='unapproved-server',
 resource:f=>f.nodes.find(n=>n.type==='mcp').data.properties.enabledResources.push('private-records'),
 route:f=>f.edges.find(e=>e.data.edgeType==='standard').target=f.nodes.find(n=>n.type==='mcp').id,
 manifest:f=>f.gloriaWorkflow.stageManifest.runtime.parallel_barriers.merge_parallel.pop(),
 source:f=>f.gloriaWorkflow.stageManifest.sourceHashes['config/policy_rules.yaml']='0'.repeat(64),
 authority:f=>f.gloriaWorkflow.applicationTool.input.customer_id='string',
 flow_policy:f=>f.behaviorRules=[{effect:'allow',action:'*'}],
};
for(const [name,mutate] of Object.entries(cases)) {
 const flow=structuredClone(result.flow); mutate(flow);
 assert.throws(()=>assertBridge(flow,DEFAULT_BINDINGS,result.manifest,result.flujo),undefined,name);
}
console.log(JSON.stringify(Object.keys(cases)));
"""
        result = node_run("--input-type=module", "-e", code, str(FLUJO))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)), 11)

    def test_cli_rejects_unknown_duplicate_and_half_bound_arguments(self):
        for args in (("--install",), ("--check", "--check"), ("--model-id", "partial")):
            result = node_run("scripts/build_gloria_graph.mjs", "--flujo-root", str(FLUJO), *args)
            self.assertNotEqual(result.returncode, 0)

    def test_saved_file_hash_covers_metadata_and_requires_exact_reviewed_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "saved.json"
            flags = ("--flujo-root", str(FLUJO), "--model-id", "qualified-test-model",
                     "--workflow-server", "qualified-test-server")
            built = node_run("scripts/build_gloria_graph.mjs", *flags, "--out", str(saved))
            self.assertEqual(built.returncode, 0, built.stderr)
            original = json.loads(built.stdout)
            graph = json.loads(saved.read_text(encoding="utf-8"))
            graph.update(createdAt=1790827200000, updatedAt=1790827200000, favorite=False)
            saved.write_text(json.dumps(graph), encoding="utf-8")
            checked = node_run("scripts/build_gloria_graph.mjs", *flags, "--saved-flow", str(saved))
            self.assertEqual(checked.returncode, 0, checked.stderr)
            qualified = json.loads(checked.stdout)
            self.assertEqual(qualified["scope"], "supplied_saved_file_only_not_live_readback")
            self.assertNotEqual(qualified["graphHash"], original["graphHash"])
            self.assertFalse(qualified["installed"])
            next(node for node in graph["nodes"] if node["type"] == "mcp")["data"]["properties"]["enabledTools"].append("get_my_transaction")
            saved.write_text(json.dumps(graph), encoding="utf-8")
            rejected = node_run("scripts/build_gloria_graph.mjs", *flags, "--saved-flow", str(saved))
            self.assertNotEqual(rejected.returncode, 0)

    def test_check_rejects_a_stale_protected_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / "stale.json"
            graph = dict(self.graph)
            graph["description"] += " unreviewed change"
            stale.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
            result = node_run("scripts/build_gloria_graph.mjs", "--flujo-root", str(FLUJO),
                              "--check", "--out", str(stale))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("regenerate and review", result.stderr)

    def test_policy_dependency_and_action_source_changes_independently_requalify_graph(self):
        code = """
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {build,assertBridge,DEFAULT_BINDINGS,REPO_ROOT} from './scripts/build_gloria_graph.mjs';
const root=fs.mkdtempSync(path.join(os.tmpdir(),'gloria-qualified-sources-'));
const original=build(process.argv[1]);
try {
 for(const relative of Object.keys(original.manifest.sourceHashes)) {
  const destination=path.join(root,relative);
  fs.mkdirSync(path.dirname(destination),{recursive:true});
  fs.copyFileSync(path.join(REPO_ROOT,relative),destination);
 }
 const unchanged=build(process.argv[1],DEFAULT_BINDINGS,root);
 assert.equal(unchanged.report.graphHash,original.report.graphHash);
 const cases=['resources/policies/transaction_dispute_policy.md','requirements-gloria.txt',
  'banking_mcp/actions.py','frontend/server/chat.py','frontend/server/app.py'];
 for(const relative of cases) {
  const filename=path.join(root,relative),before=fs.readFileSync(filename);
  fs.appendFileSync(filename,'\\n# Independent protected-source mutation for qualification.\\n');
  const changed=build(process.argv[1],DEFAULT_BINDINGS,root);
  assert.notEqual(changed.report.graphHash,original.report.graphHash,relative);
  assert.notEqual(changed.report.stageManifestHash,original.report.stageManifestHash,relative);
  assert.equal(changed.flow.nodes.find(n=>n.type==='process').data.properties.boundModel,
   original.flow.nodes.find(n=>n.type==='process').data.properties.boundModel);
  assert.throws(()=>assertBridge(original.flow,DEFAULT_BINDINGS,changed.manifest,changed.flujo),undefined,relative);
  fs.writeFileSync(filename,before);
 }
 const rebound=build(process.argv[1],{modelId:'different-model',workflowServer:DEFAULT_BINDINGS.workflowServer},root);
 assert.notEqual(rebound.report.graphHash,original.report.graphHash);
 assert.equal(rebound.report.stageManifestHash,original.report.stageManifestHash);
 console.log(JSON.stringify({mutations:cases.length,modelIndependent:true}));
} finally {
 assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));
 assert(path.basename(root).startsWith('gloria-qualified-sources-'));
 fs.rmSync(root,{recursive:true,force:true});
}
"""
        result = node_run("--input-type=module", "-e", code, str(FLUJO))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"mutations": 5, "modelIndependent": True})


if __name__ == "__main__":
    unittest.main()
