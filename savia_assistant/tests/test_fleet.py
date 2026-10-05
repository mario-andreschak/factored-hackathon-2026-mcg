import asyncio
import json
import uuid

import httpx
import pytest

from savia_assistant import InquiryService
from savia_assistant.fleet import FleetBinding, RecoveredFleet, canonical, configured_fleet, digest, normalized_snapshots


def snapshots():
    def node(node_id,type,properties):
        return {"id":node_id,"type":type,"data":{"label":type,"properties":properties}}
    return {
        "swarm_agent":{"id":"installed-agent-v1","name":"swarm_agent","nodes":[
            node("agent-start","start",{"promptTemplate":"Inspect permitted evidence and report an informational enum."}),
            node("agent-process","process",{"boundModel":"owner-model","maxTurns":200,"promptTemplate":"Do the assigned task."}),
            node("agent-finish","finish",{})],"edges":[{"source":"agent-start","target":"agent-process"},{"source":"agent-process","target":"agent-finish"}]},
        "swarm_supervisor":{"id":"installed-root-v1","name":"swarm_supervisor","nodes":[
            node("root-start","start",{"promptTemplate":"Coordinate; check independent evidence and the exact final proposal."}),
            node("root-process","process",{"boundModel":"owner-model","maxTurns":600,"promptTemplate":"Supervise the accepted goal."}),
            node("root-agents","subflow",{"subflowId":"installed-agent-v1","concurrencyLimit":9,"inputMode":"isolated","outputMode":"final-only"}),
            node("root-finish","finish",{})],"edges":[{"source":"root-start","target":"root-process"},{"source":"root-process","target":"root-agents"},{"source":"root-process","target":"root-finish"}]},
    }


class FleetHarness:
    """Fake upstream transport and owned native records; never a provider call."""
    def __init__(self, tmp_path, monkeypatch):
        self.now, self.calls, self.native, self.board = [1000], [], {}, []
        self.snapshot_overrides = {}
        self.state, self.lost_ack, self.corrupt_status = "running", False, False
        monkeypatch.setenv("TEST_FLEET_TOKEN", "controller-private-" + "a"*40)
        monkeypatch.setenv("TEST_NATIVE_TOKEN", "native-private-" + "b"*40)
        self.path = tmp_path / "owner-registry.json"
        self.snapshots = snapshots()
        self.config = {"mode":"recovered-fleet/v1", "owner_approved":True,
            "controller_origin":"http://127.0.0.1:43960", "controller_token_env":"TEST_FLEET_TOKEN",
            "registry_path":str(self.path), "source_revision":"f"*40, "template_digest":digest(normalized_snapshots(self.snapshots)),
            "model_id":"owner-model", "supervisor":{"origin":"http://127.0.0.1:43420",
                "workspace":"owned-test", "token_env":"TEST_NATIVE_TOKEN"}, "team_machines":10,
            "task_instructions":"Use the existing recovered flows; inspect permitted display evidence."}
        self.binding = FleetBinding.from_config(self.config)
        self.path.write_text(canonical({"version":1,"goals":{},"workers":{},"runs":{},"board":[]}),encoding="utf-8")
        self.fleet = RecoveredFleet(self.binding, transport=httpx.MockTransport(self.request))
        self.service = InquiryService(tmp_path / "savia", fleet=self.fleet, clock=lambda:self.now[0])
        self.case = self.service.create("alice", "No reconozco este comercio", request_id=str(uuid.uuid4()))

    def job(self):
        with self.service.connection() as db:
            return dict(db.execute("SELECT * FROM fleet_jobs WHERE case_id=?", (self.case,)).fetchone())

    def item(self, owner="alice"):
        return self.service.list(owner)["items"][0]

    def tick(self):
        asyncio.run(self.service.check(owner="alice"))
        self.now[0] += 31

    def request(self, request):
        self.calls.append((request.method,request.url.path))
        if request.method == "POST":
            assert request.url.path == "/goals"
            # Crash fence and immutable body exist before this external write.
            assert self.job()["state"] == "submitting"
            body = json.loads(request.content)
            assert self.job()["input_digest"] in body["text"]
            assert body["teamLimits"] == {"concurrency":9}
            assert "RESULT PROTOCOL" in body["text"] and "conclusion_review" in body["text"]
            self.goal = {"id":"g-owned", "text":body["text"], "state":"active"}
            self.registry = {"version":1, "goals":{"g-owned":self.goal}, "workers":{
                "w-root":{"id":"w-root","goalId":"g-owned","depth":0,"name":"supervisor",
                          "target":{"origin":self.config["supervisor"]["origin"],"workspace":"owned-test"}}},
                "runs":{"r-owned":{"id":"r-owned","workerId":"w-root","goalId":"g-owned",
                    "flowName":"swarm_supervisor","conversationId":"lead-owned","state":"running"}},"board":[]}
            self.save_registry()
            self.native["lead-owned"] = {"id":"lead-owned", "status":"running",
                "flowId":self.snapshots["swarm_supervisor"]["id"], "messages":[{"role":"user","content":body["text"]}]}
            if self.lost_ack:
                raise httpx.ReadTimeout("Synthetic lost ACK", request=request)
            return httpx.Response(201,json={"goal":self.goal,"supervisorId":"w-root","runId":"r-owned"})
        if request.url.path == "/goals/g-owned":
            return httpx.Response(200,json={"goal":self.goal,"tree":[],"board":self.board})
        if request.url.path == "/runs/r-owned":
            return httpx.Response(200,json={"runId":"r-other" if self.corrupt_status else "r-owned",
                "workerId":"w-root","workerState":"ready","state":self.state,
                "result":getattr(self,"result",None),"error":None})
        if request.url.path.startswith("/v1/chat/conversations/"):
            assert request.url.params["workspace"] == "owned-test"
            if request.url.path.endswith("/debug/state"):
                child_id = request.url.path.split("/")[-3]
                child = self.native.get(child_id)
                flow = next((flow for flow in self.snapshots.values() if child and flow["id"]==child.get("flowId")),None)
                flow = self.snapshot_overrides.get(child_id,flow)
                return httpx.Response(200 if child else 404,json={"status":child["status"] if child else "unknown",
                    "debugState":{"conversationId":child_id,"status":child["status"] if child else "unknown",
                                  "flowId":child.get("flowId") if child else None,"flowSnapshot":flow}})
            record = self.native.get(request.url.path.rsplit("/",1)[-1])
            return httpx.Response(200 if record else 404,json=record or {})
        raise AssertionError("Unexpected request: " + str(request.url))

    def save_registry(self):
        self.path.write_text(canonical(self.registry),encoding="utf-8")

    def complete(self):
        job = self.job()
        binding = {k:job[k] for k in ["case_id","request_id","input_digest","source_revision",
                                     "template_digest","goal_id","run_id"]}
        suggestions = []
        self.board = []
        def post(value):
            seq = len(self.board)+1
            self.board.append({"seq":seq,"goalId":"g-owned","author":"supervisor",
                               "topic":"savia-review","text":canonical(value),"at":1000})
            return seq
        def child(child_id, answer, supplied):
            self.native[child_id] = {"id":child_id,"status":"completed","parentConversationId":"lead-owned",
                "flowId":self.snapshots["swarm_agent"]["id"], "messages":[{"role":"user","content":canonical(supplied)},
                                                        {"role":"assistant","content":canonical(answer)}]}
        for role, suggestion in [("evidence","ask_selection"),("next_steps","ask_human")]:
            author_id, reviewer_id = "author-"+role, "reviewer-"+role
            finding = {"binding":binding,"role":role,"suggestion":suggestion,"author_conversation_id":author_id}
            finding_seq = post(finding)
            child(author_id,finding,binding)
            review = {"binding":binding,"finding_seq":finding_seq,"role":role,"suggestion":suggestion,
                      "verdict":"accept","reviewer_conversation_id":reviewer_id,
                      "check":"The suggestion uses permitted facts and claims neither bank action nor human pickup."}
            review_seq = post(review)
            child(reviewer_id,review,finding)
            suggestions.append({"role":role,"suggestion":suggestion,"author_conversation_id":author_id,
                "finding_seq":finding_seq,"reviewer_conversation_id":reviewer_id,"review_seq":review_seq})
        proposal = {"binding":binding,"suggestions":suggestions}
        conclusion = {"proposal":proposal,"verdict":"accept","reviewer_conversation_id":"fresh-checker",
                      "check":"The exact two suggestions are informational; their independent checks support the proposed reply."}
        conclusion_seq = post(conclusion)
        child("fresh-checker",conclusion,proposal)
        self.packet = {"schema_version":1,"binding":binding,"suggestions":suggestions,
                       "conclusion_review":{"reviewer_conversation_id":"fresh-checker","review_seq":conclusion_seq}}
        self.result = canonical(self.packet)
        self.state = "completed"
        self.registry["runs"]["r-owned"]["state"] = "completed"
        self.save_registry()
        self.native["lead-owned"]["status"] = "completed"
        self.native["lead-owned"]["messages"].append({"role":"assistant","content":self.result})


@pytest.fixture
def fleet(tmp_path,monkeypatch):
    return FleetHarness(tmp_path,monkeypatch)


def test_initial_submit_is_fenced_idempotent_owned_and_private(fleet):
    request_id = fleet.job()["request_id"]
    assert fleet.service.create("alice","No reconozco este comercio",request_id=request_id) == fleet.case
    with pytest.raises(ValueError,match="request_conflict"):
        fleet.service.create("alice","Otro mensaje",request_id=request_id)
    bob = fleet.service.create("bob","No reconozco este comercio",request_id=request_id)
    assert bob != fleet.case
    fleet.tick()
    fleet.tick()
    assert fleet.calls.count(("POST","/goals")) == 1
    assert fleet.item()["state"] == "team_working"
    assert "dos agentes" not in fleet.item()["status_message"]
    assert fleet.service.list("bob")["items"][0]["state"] == "queued"
    public = canonical(fleet.item())
    for private in ["g-owned","r-owned","w-root","lead-owned",request_id,fleet.binding.controller_token,
                    fleet.binding.supervisor_token,fleet.job()["input_digest"],fleet.binding.registry_path]:
        assert private not in public
    assert fleet.binding.controller_token not in canonical(fleet.job())
    assert fleet.binding.supervisor_token not in canonical(fleet.job())
    assert fleet.item()["execution"]["observed_conversations"] is None


def test_lost_ack_is_held_across_restart_and_blocks_new_submit(fleet):
    fleet.lost_ack = True
    fleet.tick()
    assert fleet.job()["state"] == "held" and fleet.job()["goal_id"] is None
    snapshot = fleet.path.read_bytes()
    fleet.service = InquiryService(fleet.service.path.parent,fleet=fleet.fleet,clock=lambda:fleet.now[0])
    fleet.service.create("alice","Una consulta nueva")
    for _ in range(3):
        fleet.tick()
    assert fleet.calls == [("POST","/goals")]
    assert fleet.path.read_bytes() == snapshot
    assert fleet.service.list("alice")["items"][-1]["state"] == "needs_attention"
    with pytest.raises(ValueError,match="review_required"):
        fleet.service.resolve("alice",fleet.case)


def test_known_run_restarts_read_only_unknown_never_replays(fleet):
    fleet.tick()
    fleet.service = InquiryService(fleet.service.path.parent,fleet=fleet.fleet,clock=lambda:fleet.now[0])
    fleet.tick()
    assert fleet.item()["state"] == "team_working"
    fleet.state = "unknown"
    fleet.tick()
    cursor = fleet.item()["voice_update"]["version"]
    fleet.tick()
    assert fleet.job()["state"] == "held" and fleet.item()["state"] == "needs_attention"
    assert fleet.item()["voice_update"]["version"] == cursor
    assert fleet.calls.count(("POST","/goals")) == 1
    assert fleet.item()["workers"] == []


def test_crash_fence_before_submit_does_not_replay_and_binding_removal_never_falls_back(fleet):
    with fleet.service.connection() as db:
        db.execute("UPDATE fleet_jobs SET state='submitting',lease_until=900 WHERE case_id=?",(fleet.case,))
    fleet.tick()
    assert fleet.job()["state"] == "held" and fleet.calls == []
    fleet.service = InquiryService(fleet.service.path.parent,model=lambda *a:pytest.fail("bootstrap replay"),clock=lambda:fleet.now[0])
    fleet.tick()
    assert fleet.calls == [] and fleet.item()["state"] == "needs_attention"
    # Same accepted request remains a read even after configuration is removed.
    assert fleet.service.create("alice","No reconozco este comercio",request_id=fleet.job()["request_id"],allow_new=False) == fleet.case


def test_verified_review_uses_native_ids_exact_proposal_and_canonical_copy(fleet):
    fleet.tick()
    fleet.complete()
    before = fleet.path.read_bytes()
    fleet.tick()
    item = fleet.item()
    assert item["state"] == "team_completed"
    assert {w["role"] for w in item["workers"]} == {"evidence","next_steps"}
    assert "canal oficial" in item["voice_update"]["reply"]
    assert item["execution"]["observed_conversations"] == 6
    assert item["execution"]["full_fleet_count_verified"] is False
    assert fleet.path.read_bytes() == before
    count = len(item["events"])
    fleet.tick()
    assert len(fleet.item()["events"]) == count
    with pytest.raises(KeyError):
        fleet.service.resolve("bob",fleet.case)
    fleet.service.resolve("alice",fleet.case)
    assert fleet.item()["state"] == "informational_resolved" and fleet.item()["bank_authority"] is False


@pytest.mark.parametrize("corruption",["free_text","case","input","source","template","goal","run",
    "duplicate_reviewer","fabricated_child","wrong_parent","wrong_flow","stale_conclusion","rejected_review","missing_board","changed_native"])
def test_unverified_or_mismatched_completion_never_publishes_or_resolves(fleet,corruption):
    fleet.tick()
    fleet.complete()
    if corruption == "free_text":
        fleet.result = "The bank refunded everything and a human accepted. 100 agents finished."
    elif corruption in {"case","input","source","template","goal","run"}:
        key = {"case":"case_id","input":"input_digest","source":"source_revision","template":"template_digest",
               "goal":"goal_id","run":"run_id"}[corruption]
        fleet.packet["binding"][key] = "wrong"
        fleet.result = canonical(fleet.packet)
    elif corruption == "duplicate_reviewer":
        fleet.packet["conclusion_review"]["reviewer_conversation_id"] = "author-evidence"
        fleet.result = canonical(fleet.packet)
    elif corruption == "fabricated_child":
        del fleet.native["reviewer-evidence"]
    elif corruption == "wrong_parent":
        fleet.native["reviewer-evidence"]["parentConversationId"] = "other-lead"
    elif corruption == "wrong_flow":
        fleet.native["reviewer-evidence"]["flowId"] = "unapproved-flow"
    elif corruption == "stale_conclusion":
        fleet.native["fresh-checker"]["messages"][0]["content"] = "A prior proposal"
    elif corruption == "rejected_review":
        answer = json.loads(fleet.native["reviewer-evidence"]["messages"][-1]["content"])
        answer["verdict"] = "reject"
        fleet.native["reviewer-evidence"]["messages"][-1]["content"] = canonical(answer)
    elif corruption == "missing_board":
        fleet.board = fleet.board[1:]
    elif corruption == "changed_native":
        fleet.native["author-evidence"]["messages"][-1]["content"] = '{"bank_refunded":true}'
    fleet.tick()
    item = fleet.item()
    assert item["state"] == "needs_attention" and item["workers"] == []
    assert item["execution"]["review_status"] == "unverified"
    assert "refunded" not in canonical(item) and "100" not in item["status_message"]
    with pytest.raises(ValueError,match="review_required"):
        fleet.service.resolve("alice",fleet.case)
    assert fleet.calls.count(("POST","/goals")) == 1


def test_wrong_original_run_or_registry_identity_is_not_adopted(fleet):
    fleet.tick()
    fleet.corrupt_status = True
    fleet.tick()
    assert fleet.job()["state"] == "held"
    assert fleet.item()["state"] == "needs_attention"
    assert fleet.calls.count(("POST","/goals")) == 1


def test_horizon_pauses_unresolved_case_without_bank_or_human_claim(fleet):
    fleet.tick()
    fleet.now[0] += fleet.service.horizon
    fleet.tick()
    item = fleet.item()
    assert item["state"] == "needs_attention" and item["next_check_at"] is None
    assert "sigue pendiente" in item["next_step"]
    assert "human_working" not in canonical(item)
    assert fleet.calls == [("POST","/goals")]


def test_binding_is_explicit_private_and_default_bootstrap(fleet):
    assert configured_fleet({}) is None and configured_fleet({"mode":"bootstrap"}) is None
    for updates in [{"owner_approved":False},{"controller_origin":"http://remote.example"},
                    {"template_digest":"missing"},{"team_machines":100},{"registry_path":"relative.json"}]:
        with pytest.raises(ValueError):
            FleetBinding.from_config({**fleet.config,**updates})
    assert fleet.binding.controller_token not in repr(fleet.binding)
    assert fleet.binding.supervisor_token not in canonical(fleet.binding.pin())


def test_delayed_ack_cannot_overwrite_expired_submission_hold(fleet):
    async def scenario():
        ready, release = asyncio.Event(), asyncio.Event()
        original = fleet.fleet.submit_goal
        async def delayed(body):
            ack = await original(body)
            ready.set()
            await release.wait()
            return ack
        fleet.fleet.submit_goal = delayed
        first = asyncio.create_task(fleet.service.check(owner="alice"))
        await ready.wait()
        fleet.now[0] = fleet.job()["lease_until"]+1
        restarted = InquiryService(fleet.service.path.parent,fleet=fleet.fleet,clock=lambda:fleet.now[0])
        await restarted.check(owner="alice")
        assert fleet.job()["state"] == "held"
        cursor = fleet.item()["voice_update"]["version"]
        release.set()
        await first
        assert fleet.job()["state"] == "held" and fleet.job()["goal_id"] is None
        assert fleet.item()["state"] == "needs_attention"
        assert fleet.item()["voice_update"]["version"] == cursor
        assert fleet.calls.count(("POST","/goals")) == 1
    asyncio.run(scenario())


def test_stale_completed_review_cannot_overwrite_newer_unknown_hold(fleet):
    fleet.tick()
    fleet.complete()
    async def scenario():
        ready, release = asyncio.Event(), asyncio.Event()
        original = fleet.fleet.reviewed_result
        async def delayed(*args):
            result = await original(*args)
            ready.set()
            await release.wait()
            return result
        fleet.fleet.reviewed_result = delayed
        first = asyncio.create_task(fleet.service.check(owner="alice"))
        await ready.wait()
        fleet.now[0] = fleet.job()["lease_until"]+1
        fleet.state = "unknown"
        restarted = InquiryService(fleet.service.path.parent,fleet=fleet.fleet,clock=lambda:fleet.now[0])
        await restarted.check(owner="alice")
        assert fleet.job()["state"] == "held"
        cursor = fleet.item()["voice_update"]["version"]
        release.set()
        await first
        assert fleet.job()["state"] == "held" and fleet.job()["review"] is None
        assert fleet.item()["workers"] == [] and fleet.item()["state"] == "needs_attention"
        assert fleet.item()["voice_update"]["version"] == cursor
        assert fleet.calls.count(("POST","/goals")) == 1
    asyncio.run(scenario())


def test_real_human_acceptance_invalidates_inflight_review_without_claiming_delivery(fleet):
    fleet.tick()
    fleet.complete()
    async def scenario():
        ready, release = asyncio.Event(), asyncio.Event()
        original = fleet.fleet.reviewed_result
        async def delayed(*args):
            result = await original(*args)
            ready.set()
            await release.wait()
            return result
        fleet.fleet.reviewed_result = delayed
        task = asyncio.create_task(fleet.service.check(owner="alice"))
        await ready.wait()
        fleet.service.accept_human("alice",fleet.case,accepted_by="authenticated-operator")
        release.set()
        await task
        assert fleet.job()["state"] == "human_owned" and fleet.job()["review"] is None
        assert fleet.item()["state"] == "human_working" and fleet.item()["workers"] == []
    asyncio.run(scenario())


def test_changed_runtime_binding_is_held_before_any_submit(fleet):
    changed = FleetBinding.from_config({**fleet.config,"source_revision":"a"*40})
    fleet.service.fleet = RecoveredFleet(changed,transport=httpx.MockTransport(fleet.request))
    fleet.tick()
    assert fleet.job()["state"] == "held" and fleet.calls == []


def test_immutable_body_and_accepted_owner_join_are_checked_before_dispatch(fleet):
    with fleet.service.connection() as db:
        body = json.loads(fleet.job()["request_body"])
        body["text"] = "Different instructions"
        db.execute("UPDATE fleet_jobs SET request_body=? WHERE case_id=?",(canonical(body),fleet.case))
    fleet.tick()
    assert fleet.job()["state"] == "held" and fleet.calls == []


def test_changed_source_cannot_bypass_an_existing_hold_on_same_lane(fleet):
    fleet.lost_ack = True
    fleet.tick()
    changed = FleetBinding.from_config({**fleet.config,"source_revision":"a"*40})
    fleet.service.fleet = RecoveredFleet(changed,transport=httpx.MockTransport(fleet.request))
    new_case = fleet.service.create("alice","Another inquiry")
    fleet.tick()
    assert fleet.calls == [("POST","/goals")]
    with fleet.service.connection() as db:
        assert db.execute("SELECT state FROM fleet_jobs WHERE case_id=?",(new_case,)).fetchone()[0] == "intent"


def test_previous_board_references_are_retained_when_latest_window_moves(fleet):
    fleet.tick()
    fleet.complete()
    # Observe the board before native proof is complete.
    fleet.native["fresh-checker"]["status"] = "running"
    fleet.tick()
    assert fleet.item()["state"] == "needs_attention"
    fleet.native["fresh-checker"]["status"] = "completed"
    fleet.board = []  # Existing GET is only the latest window; private cache remains.
    fleet.tick()
    assert fleet.item()["state"] == "team_completed"


def test_deadline_expiring_during_review_prevents_late_publication(fleet):
    fleet.tick()
    fleet.complete()
    async def scenario():
        original = fleet.fleet.reviewed_result
        async def delayed(*args):
            result = await original(*args)
            fleet.now[0] += fleet.service.horizon
            return result
        fleet.fleet.reviewed_result = delayed
        await fleet.service.check(owner="alice")
        assert fleet.job()["state"] == "held" and fleet.job()["review"] is None
        assert fleet.item()["state"] == "needs_attention" and fleet.item()["workers"] == []
    asyncio.run(scenario())


def test_held_lane_blocks_new_dispatch_without_starving_original_run_polling(fleet):
    fleet.tick()  # A already has its original handles.
    queued = fleet.service.create("alice","Queued inquiry B")
    held = fleet.service.create("alice","Held inquiry C")
    with fleet.service.connection() as db:
        db.execute("UPDATE fleet_jobs SET next_poll_at=1040 WHERE case_id=?",(fleet.case,))
        db.execute("UPDATE fleet_jobs SET next_poll_at=1030 WHERE case_id=?",(queued,))
        record = db.execute("SELECT * FROM fleet_jobs WHERE case_id=?",(held,)).fetchone()
        fleet.service._fleet_state(db,record,"held","needs_attention",reason="synthetic_original_unknown")
    fleet.now[0] = 1050
    before = len(fleet.calls)
    fleet.tick()
    assert ("GET","/runs/r-owned") in fleet.calls[before:]
    original = next(item for item in fleet.service.list("alice")["items"] if item["id"]==fleet.case)
    assert original["state"] == "team_working"
    assert fleet.calls.count(("POST","/goals")) == 1
    with fleet.service.connection() as db:
        assert db.execute("SELECT state FROM fleet_jobs WHERE case_id=?",(queued,)).fetchone()[0] == "intent"


def test_regenerated_compiler_ids_keep_semantic_pin_and_save_actual_execution_ids(fleet):
    compiled = canonical(fleet.snapshots)
    identities = [flow["id"] for flow in fleet.snapshots.values()]
    identities += [node["id"] for flow in fleet.snapshots.values() for node in flow["nodes"]]
    for index,old in enumerate(sorted(identities,key=len,reverse=True)):
        compiled = compiled.replace(old,"compiled-new-"+str(index))
    fleet.snapshots = json.loads(compiled)
    assert digest(normalized_snapshots(fleet.snapshots)) == fleet.binding.template_digest
    fleet.tick()
    fleet.complete()
    fleet.tick()
    assert fleet.item()["state"] == "team_completed"
    saved = json.loads(fleet.job()["installation"])
    assert saved["provenance"] == "original_native_execution_snapshots"
    assert saved["flow_ids"] == {name:flow["id"] for name,flow in fleet.snapshots.items()}
    assert saved["snapshot_digests"] == {name:digest(flow) for name,flow in fleet.snapshots.items()}
    assert ("GET","/v1/chat/conversations/lead-owned/debug/state") in fleet.calls
    assert "compiled-new-" not in canonical(fleet.item())


@pytest.mark.parametrize("corruption",["missing","prompt","model","concurrency"])
def test_original_execution_snapshot_required_and_semantics_pinned(fleet,corruption):
    fleet.tick()
    fleet.complete()
    if corruption == "missing":
        fleet.snapshot_overrides["reviewer-evidence"] = None
    else:
        flow = fleet.snapshots["swarm_supervisor"]
        if corruption == "concurrency":
            flow["nodes"][2]["data"]["properties"]["concurrencyLimit"] = 10
        else:
            key = "boundModel" if corruption == "model" else "promptTemplate"
            flow["nodes"][1]["data"]["properties"][key] = "different-semantics"
    fleet.tick()
    assert fleet.job()["state"] == "review_pending" and fleet.job()["installation"] is None
    assert fleet.item()["state"] == "needs_attention" and fleet.item()["workers"] == []
    assert fleet.calls.count(("POST","/goals")) == 1
    with pytest.raises(ValueError,match="review_required"):
        fleet.service.resolve("alice",fleet.case)


def test_active_lane_queues_new_goal_while_known_original_keeps_polling(fleet):
    fleet.tick()
    queued = fleet.service.create("alice","Second inquiry")
    for _ in range(3):
        fleet.tick()
    assert fleet.calls.count(("POST","/goals")) == 1
    assert fleet.calls.count(("GET","/runs/r-owned")) == 3
    with fleet.service.connection() as db:
        assert db.execute("SELECT state FROM fleet_jobs WHERE case_id=?",(queued,)).fetchone()[0] == "intent"


@pytest.mark.parametrize("occupied",["running","unknown","cleanup"])
def test_existing_workspace_ownership_hold_prevents_initial_rpc(fleet,occupied):
    state = {"version":1,"goals":{"existing":{"id":"existing"}},"workers":{
        "original":{"id":"original","goalId":"existing","target":{
            "origin":fleet.binding.supervisor["origin"],"workspace":fleet.binding.supervisor["workspace"]}}},
        "runs":{},"board":[]}
    if occupied == "cleanup":
        state["workers"]["original"]["cleanup"] = {"confirmed":False}
    else:
        state["runs"]["original"] = {"goalId":"existing","state":occupied}
    fleet.path.write_text(canonical(state),encoding="utf-8")
    before = fleet.path.read_bytes()
    fleet.tick()
    assert fleet.calls == [] and fleet.job()["state"] == "held"
    assert fleet.path.read_bytes() == before


def test_scoped_mcp_reads_same_private_owner_binding_without_runtime_calls(fleet,tmp_path,monkeypatch):
    from savia_assistant.mcp import configured_service
    config = tmp_path / "private-host-config.json"
    config.write_text(canonical({"inquiries":fleet.config}),encoding="utf-8")
    monkeypatch.setenv("BANKING_CONFIG_FILE",str(config))
    monkeypatch.setenv("SAVIA_INQUIRY_STATE_DIR",str(tmp_path / "mcp-cases"))
    service = configured_service()
    assert service.fleet.binding.pin() == fleet.binding.pin()
    assert fleet.calls == []
