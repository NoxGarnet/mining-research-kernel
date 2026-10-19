"""Deterministic, read-only Markdown views of saved research records."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
from html import escape
import json
import re

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.source_identity import identities_match, paper_identity, primary_identity_label


_MAX_LINEAGE = 64
_RECORD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)


def _text(value, fallback="当前阅读范围未报告"):
    if value is None or value == "":
        value = fallback
    if not isinstance(value, str):
        value = str(value)
    # Escape HTML and Markdown structure while retaining readable newlines.
    value = re.sub(r"(?i)(?<![a-z0-9])[a-z]:(?:\\|/(?!/))[^\s<>\"']+|\\\\[^\s<>\"']+|/(?:Users|home|tmp|mnt|workspace)/[^\s<>\"']+",
                   "[本机路径已省略]", value)
    value = escape(value, quote=True).replace("|", "&#124;").replace("\\", "&#92;")
    value = value.replace("[", "&#91;").replace("]", "&#93;").replace("(", "&#40;").replace(")", "&#41;")
    value = value.replace("*", "&#42;").replace("_", "&#95;").replace("!", "&#33;")
    value = re.sub(r"#(?![0-9]+;|x[0-9A-Fa-f]+;)", "&#35;", value)
    value = re.sub(r"(`+)", lambda m: "&#96;" * len(m.group(0)), value)
    return "<br>".join(value.splitlines())


def _code_id(value):
    if isinstance(value, str) and _RECORD_ID.fullmatch(value):
        return f"`{value}`"
    return f"`{_text(value)}`"


def _records(store):
    by_version = {}
    latest = {}
    task_decisions = {}
    for transaction in store.list_transactions():
        decisions_in_transaction = {record.get("id"): record for record in transaction.get("records", [])
                                   if record.get("type") == "Decision"}
        for record in transaction.get("records", []):
            by_version[(record.get("id"), record.get("revision"))] = record
            if record.get("revision", 0) >= latest.get(record.get("id"), {}).get("revision", 0):
                latest[record.get("id")] = record
            if record.get("type") == "TaskState":
                decision_id = record.get("packet", {}).get("review_record_ref")
                if decision_id in decisions_in_transaction:
                    task_decisions[(record.get("id"), record.get("revision"))] = decisions_in_transaction[decision_id]
    return by_version, latest, task_decisions


def _decision_for_task(state, latest, task_decisions=None):
    exact = (task_decisions or {}).get((state.get("id"), state.get("revision")))
    if exact:
        return exact
    packet = state.get("packet", {})
    decision_id = packet.get("review_record_ref")
    if not isinstance(decision_id, str):
        results = state.get("operation_results", {})
        decision_id = next((v.get("decision_id") for v in reversed(list(results.values()))
                            if isinstance(v, Mapping) and isinstance(v.get("decision_id"), str)), None)
    decision = latest.get(decision_id) if decision_id else None
    return decision if decision and decision.get("type") == "Decision" else None


def _paper_capture(asset):
    if not isinstance(asset, Mapping) or asset.get("asset_kind") != "zotero_reading_capture":
        return None
    payload = asset.get("payload", {})
    capture = payload.get("request", {}).get("capture", {}) if isinstance(payload, Mapping) else {}
    item = capture.get("item") if isinstance(capture, Mapping) else None
    return capture if isinstance(item, Mapping) and item else None


def _reading_observation(asset):
    if not isinstance(asset, Mapping) or asset.get("asset_kind") != "reading_observation":
        return None
    from mining_research_kernel.reading_observation import validate_observation
    return validate_observation(asset.get("payload", {}).get("request", {}).get("observation"))


def _asset_caption(asset):
    if not asset:
        return "来源历史版本不可用"
    payload = asset.get("payload", {})
    capture = _paper_capture(asset)
    if capture:
        item = capture["item"]
        return item.get("title") or item.get("key") or asset["id"]
    observation = _reading_observation(asset)
    if observation:
        source = observation["source"]
        identity = "; ".join(str(value) for value in (source.get("doi"), source.get("url")) if value)
        return (source.get("title") or source["source_id"]) + (f" · {identity}" if identity else "")
    result = payload.get("documentation_result", {})
    citation = result.get("citation", {}) if isinstance(result, Mapping) else {}
    return citation.get("document_family") or citation.get("source_id") or asset["id"]


def _coverage(asset):
    payload = asset.get("payload", {})
    observation = _reading_observation(asset)
    if observation:
        good = [p for p in observation["passages"] if p["status"] == "read"]
        bad = [p for p in observation["passages"] if p["status"] != "read"]
        scopes = ", ".join(p["locator"]["value"] for p in good)
        gaps = list(observation["limitations"])
        gaps.extend(limit for passage in observation["passages"] for limit in passage["limitations"])
        gaps.extend("未成功读取：" + p["locator"]["value"] for p in bad)
        gaps.extend("阅读文本哈希未知：" + p["locator"]["value"] for p in good if p["text_sha256"] is None)
        return scopes or "没有成功读取的定位范围", "; ".join(dict.fromkeys(gaps))
    capture = _paper_capture(asset)
    if capture:
        pages = capture.get("pages", [])
        good = [p for p in pages if isinstance(p, Mapping) and p.get("status") == "read"]
        bad = [p for p in pages if isinstance(p, Mapping) and p.get("status") != "read"]
        ranges = ", ".join(f"{p.get('attachment_key')} pp. {p.get('start_page')}–{p.get('end_page')}" for p in good)
        gaps = ", ".join(f"{p.get('attachment_key')} ({p.get('status')})" for p in bad)
        return ranges or "当前阅读范围未报告", gaps
    result = payload.get("documentation_result", {})
    citation = result.get("citation", {}) if isinstance(result, Mapping) else {}
    passages = result.get("passages", []) if isinstance(result, Mapping) else []
    locator_values = [p.get("locator") for p in passages if isinstance(p, Mapping) and p.get("locator")]
    locator_values.extend(value for value in (citation.get("page"), citation.get("anchor"))
                          if value and value not in locator_values)
    uncovered = result.get("uncovered", []) if isinstance(result, Mapping) else []
    locator = ", ".join(str(item) for item in locator_values if item is not None)
    gaps = list(map(str, uncovered))
    if citation.get("trust_class") == "community_mcp" and not citation.get("document_build"):
        gaps.append("community MCP response has no document build/version")
    return (locator or "当前阅读范围未报告",
            "; ".join(gaps) or "未覆盖范围未报告")


def _doc_metadata(asset):
    payload = asset.get("payload", {}) if isinstance(asset, Mapping) else {}
    result = payload.get("documentation_result", {}) if isinstance(payload, Mapping) else {}
    citation = result.get("citation", {}) if isinstance(result, Mapping) else {}
    return result, citation


def _payload_sha256(asset):
    encoded = json.dumps(asset.get("payload"), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pinned_sources(assessment, versions):
    bindings = assessment.get("source_bindings", []) if isinstance(assessment, Mapping) else []
    if not isinstance(bindings, list):
        raise ValueError("saved source_bindings is malformed")
    assets, evidence = {}, {}
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise ValueError("saved source binding is malformed")
        aid, revision = binding.get("asset_ref"), binding.get("revision")
        asset = versions.get((aid, revision))
        if asset is None:
            assets[aid] = None
            for eid in binding.get("evidence_refs", []):
                evidence[eid] = None
            continue
        if asset.get("type") != "Asset":
            raise ValueError(f"pinned source record is not an Asset: {aid}@{revision}")
        expected_hash = binding.get("sha256")
        if not isinstance(expected_hash, str) or asset.get("content_sha256") != expected_hash:
            raise ValueError(f"pinned Asset hash does not match saved source binding: {aid}@{revision}")
        if _payload_sha256(asset) != expected_hash:
            raise ValueError(f"pinned Asset payload hash is corrupt: {aid}@{revision}")
        assets[aid] = asset
        evidence_revisions = binding.get("evidence_revisions", {})
        if not isinstance(evidence_revisions, Mapping):
            raise ValueError(f"pinned Evidence revisions are malformed for Asset {aid}")
        for eid in binding.get("evidence_refs", []):
            erev = evidence_revisions.get(eid)
            item = versions.get((eid, erev)) if isinstance(erev, int) else None
            if item is None:
                evidence[eid] = None
                continue
            if item.get("type") != "Evidence" or item.get("asset_ref") != aid:
                raise ValueError(f"pinned Evidence does not bind to saved Asset {aid}: {eid}@{erev}")
            evidence[eid] = item
    return assets, evidence


def _render_comparison(lines, comparison, assets, evidence, bindings):
    lines += ["## 对比条件与方法", "",
              "| 来源 | 维度 | 状态、观察与解释 | 引文 |",
              "|---|---|---|---|"]
    for source_index, source in enumerate(comparison.get("sources", []), 1):
        if not isinstance(source, Mapping):
            continue
        aid = source.get("asset_ref")
        asset = assets.get(aid)
        binding = bindings.get(aid)
        if binding is None:
            raise ValueError(f"comparison source has no saved historical binding: {aid}")
        asset = asset or {}
        _doc_result, doc = _doc_metadata(asset)
        source_context = []
        trust_class = doc.get("trust_class")
        if isinstance(trust_class, str):
            source_context.append("来源信任：" + _text(trust_class))
        if trust_class == "community_mcp" and not doc.get("document_build"):
            source_context.append("社区 MCP 返回未给出版本")
        locator = doc.get("anchor") or doc.get("page")
        if locator:
            source_context.append("定位：" + _text(str(locator)))
        short_ref = aid if not isinstance(aid, str) or len(aid) <= 18 else "…" + aid[-14:]
        source_alias = f"S{source_index} · {short_ref}"
        for dimension, cell in source.get("dimensions", {}).items():
            if not isinstance(cell, Mapping):
                continue
            citations = []
            for cite in cell.get("citations", []):
                if not isinstance(cite, Mapping):
                    continue
                eid = cite.get("evidence_id", "")
                if eid not in binding.get("evidence_refs", []):
                    raise ValueError(f"comparison citation Evidence is not bound to Asset {aid}: {eid}")
                ev = evidence.get(eid)
                ev_revision = binding.get("evidence_revisions", {}).get(eid, "?")
                ev_label = f"{eid} r{ev_revision}" if ev else f"{eid}（历史 Evidence 版本不可用）"
                if "page_range" in cite:
                    pg = cite["page_range"]
                    citations.append(f"{ev_label} · {cite.get('attachment_key')} pp. {pg.get('start_page')}–{pg.get('end_page')}")
                else:
                    citations.append(f"{ev_label} · {cite.get('locator')}")
            is_reported = cell.get("status") == "reported"
            observation = (("已记录：" + _text(cell.get("value"))) if is_reported else
                           "当前阅读范围未报告")
            explanation = _text(cell.get("interpretation"))
            context_text = ("<br>" + "；".join(source_context)) if source_context else ""
            lines.append(f"| {_text(source_alias)} | {_text(dimension)} | {observation}<br>解释：{explanation}{context_text} | "
                         f"{_text('；'.join(citations) or None)} |")
    for diff in comparison.get("differences", []):
        if isinstance(diff, Mapping):
            lines += ["", f"**差异（{_text(diff.get('dimension'))}）：** {_text(diff.get('explanation'))}  ",
                      f"**可迁移性：** {_text(diff.get('transferability'))}"]
    lines += ["", "**限制：** " + ("；".join(map(_text, comparison.get("limitations", []))) or "当前未记录")]


def _source_identity(asset, asset_ref):
    return primary_identity_label(asset, asset_ref)


def _decision_sources(decision, versions, previous_sources=None):
    source_decision = _source_decision_ancestor(decision, versions)
    if source_decision is None:
        return {}, None
    assessment = source_decision.get("assessment", {})
    comparison = assessment.get("literature_comparison") if isinstance(assessment, Mapping) else None
    pinned_assets, _ = _pinned_sources(assessment, versions)
    bindings = {b.get("asset_ref"): b for b in assessment.get("source_bindings", []) if isinstance(b, Mapping)}
    rows = {}
    source_rows = (comparison.get("sources", []) if isinstance(comparison, Mapping) else
                   [{"asset_ref": b.get("asset_ref"), "dimensions": {}}
                    for b in assessment.get("source_bindings", []) if isinstance(b, Mapping)])
    for row in source_rows:
        if not isinstance(row, Mapping):
            continue
        aid = row.get("asset_ref")
        binding = bindings.get(aid, {})
        asset = pinned_assets.get(aid) or {}
        identity_info = paper_identity(asset)
        identity = _source_identity(asset, aid)
        match_keys = []
        if previous_sources:
            for previous_key, previous_row in previous_sources.items():
                previous_identity = previous_row.get("identity")
                if identity_info and isinstance(previous_identity, Mapping) and identities_match(
                        identity_info, previous_identity):
                    match_keys.append(previous_key)
        if len(match_keys) > 1:
            raise ValueError("source identity matches multiple records in the preceding research step")
        if match_keys:
            identity = match_keys[0]
        if identity_info is None:
            identity_info = {"keys": {("asset", aid)}, "source_id": None, "doi": None}
        capture = _paper_capture(asset)
        pages = capture.get("pages", []) if isinstance(capture, Mapping) else []
        coverage = sorted({(p.get("attachment_key"), p.get("start_page"), p.get("end_page"), p.get("status"))
                           for p in pages if isinstance(p, Mapping)})
        observation = _reading_observation(asset)
        if observation:
            coverage = sorted((p["locator"]["kind"], p["locator"]["value"], p["status"])
                              for p in observation["passages"])
        status = {name: cell.get("status") for name, cell in row.get("dimensions", {}).items()
                  if isinstance(cell, Mapping)}
        refs = sorted({cite.get("evidence_id") for cell in row.get("dimensions", {}).values()
                       if isinstance(cell, Mapping) for cite in cell.get("citations", [])
                       if isinstance(cite, Mapping) and isinstance(cite.get("evidence_id"), str)})
        rows[identity] = {"asset_ref": aid, "coverage": coverage, "statuses": status,
                          "evidence": refs, "caption": _asset_caption(asset), "identity": identity_info}
    current_judgment = decision.get("judgment", {})
    return rows, current_judgment.get("summary") or (comparison.get("summary") if isinstance(comparison, Mapping) else None)


def _source_decision_ancestor(decision, versions):
    """Follow bounded incremental inheritance until the saved source judgment is found."""
    current = decision
    seen = set()
    for _ in range(_MAX_LINEAGE):
        if not isinstance(current, Mapping) or current.get("type") != "Decision":
            return None
        key = (current.get("id"), current.get("revision"))
        if key in seen:
            raise ValueError("incremental Decision inheritance contains a cycle")
        seen.add(key)
        assessment = current.get("assessment", {})
        if isinstance(assessment, Mapping) and (
                isinstance(assessment.get("literature_comparison"), Mapping)
                or isinstance(assessment.get("source_bindings"), list)):
            return current
        inherited = current.get("judgment", {}).get("inherited_from", {})
        if not isinstance(inherited, Mapping) or not isinstance(inherited.get("decision_id"), str):
            return None
        current = versions.get((inherited["decision_id"], inherited.get("revision")))
    raise ValueError("incremental Decision inheritance exceeds 64 records")


def _render_bound_sources(lines, assessment, assets, evidence):
    bindings = assessment.get("source_bindings", []) if isinstance(assessment, Mapping) else []
    if not isinstance(bindings, list) or not bindings:
        return
    lines += ["## 来源、版本与覆盖范围", "",
              "| 来源 | Asset 版本 | Evidence 版本 | 已保存阅读范围 | 信任与未覆盖范围 |",
              "|---|---|---|---|---|"]
    for binding in bindings:
        if not isinstance(binding, Mapping):
            continue
        aid = binding.get("asset_ref")
        asset = assets.get(aid)
        payload = asset.get("payload", {}) if isinstance(asset, Mapping) else {}
        capture = _paper_capture(asset)
        observation = _reading_observation(asset)
        citation = {}
        if observation:
            source, reader = observation["source"], observation["reader"]
            versions_text = (f"{source.get('version') or '来源版本未知'}; r{binding.get('revision')}; "
                             f"{source['source_kind']}; {reader['tool']} / {reader['method']}; "
                             f"capture {observation['captured_at']}; "
                             f"来源文件哈希（调用方声明）：{source.get('source_sha256') or '未知'}")
        elif capture:
            identity = capture.get("item", {})
            versions_text = f"capture {identity.get('version')}; r{binding.get('revision')}"
        else:
            _, citation = _doc_metadata(asset)
            versions_text = (f"{citation.get('document_family') or '文档版本未记录'} / "
                             f"{citation.get('document_build') or 'build 未记录'}; r{binding.get('revision')}")
            if citation.get("trust_class") == "community_mcp" and not citation.get("document_build"):
                versions_text += "（社区 MCP 未返回文档版本）"
        coverage, uncovered = _coverage(asset)
        trust = ("派生阅读观察；来源权威为调用方声明：" + observation["source"]["authority"] +
                 "；阅读行为、来源身份和科学结论未独立验证" if observation else
                 citation.get("trust_class") if not isinstance(capture, Mapping) else "来源未重新核验")
        ev_revs = binding.get("evidence_revisions", {})
        ev_text = ", ".join(f"{eid} r{ev_revs.get(eid, '?')}" if evidence.get(eid)
                             else f"{eid}（历史 Evidence 版本不可用）"
                             for eid in binding.get("evidence_refs", []))
        lines.append("| " + " | ".join(map(_text, [
            f"{_asset_caption(asset)} [{aid}]" if asset else f"来源历史版本不可用 [{aid}]",
            versions_text, ev_text or None, coverage, f"{trust or '信任类别未记录'}；{uncovered}",
        ])) + " |")


def _lineage(task_id, states, versions):
    result, seen, current = [], set(), task_id
    while current:
        if current in seen:
            raise ValueError(f"research continuation cycle at task {current}")
        if len(result) >= _MAX_LINEAGE:
            raise ValueError("research continuation lineage exceeds 64 tasks")
        seen.add(current)
        state = states.get(current)
        if not state or state.get("type") != "TaskState":
            if not result:
                raise ValueError(f"unknown task: {task_id}")
            break
        result.append(state)
        meta = state.get("packet", {}).get("input", {}).get("research_continuation")
        if isinstance(meta, Mapping):
            previous_id, previous_revision = meta.get("previous_task_id"), meta.get("previous_task_revision")
            state = versions.get((previous_id, previous_revision))
            if not state or state.get("type") != "TaskState":
                raise ValueError(f"continuation references unavailable TaskState revision: {previous_id}@{previous_revision}")
            states[previous_id] = state
            current = previous_id
        else:
            current = None
    result.reverse()
    return result


def render_research_report(project_root, *, task_id: str) -> str:
    """Render a stable report from records; this function performs no writes or source reads."""
    store = ResearchStore(project_root)
    versions, latest, task_decisions = _records(store)
    states = {rid: record for rid, record in latest.items() if record.get("type") == "TaskState"}
    lineage = _lineage(task_id, states, versions)
    decisions = []
    for state in lineage:
        packet = state.get("packet", {})
        meta = packet.get("input", {}).get("research_continuation")
        current_decision = _decision_for_task(state, latest, task_decisions)
        if isinstance(meta, Mapping):
            did, rev = meta.get("previous_decision_id"), meta.get("previous_decision_revision")
            prior = versions.get((did, rev))
            if not prior or prior.get("type") != "Decision":
                raise ValueError(f"continuation references unavailable Decision revision: {did}@{rev}")
            if current_decision is None:
                # A pending continuation still presents its completed base judgment as inherited context.
                current_decision = prior
            else:
                bound = current_decision.get("judgment", {}).get("inherited_from", {})
                if (isinstance(bound, Mapping) and bound.get("decision_id") == did
                        and bound.get("revision") != rev):
                    raise ValueError("current incremental Decision does not match the continuation's bound revision")
            decisions.append(current_decision)
        else:
            decisions.append(current_decision)
    for index in range(len(lineage) - 1):
        child_meta = lineage[index + 1].get("packet", {}).get("input", {}).get("research_continuation")
        if not isinstance(child_meta, Mapping):
            continue
        bound = versions.get((child_meta.get("previous_decision_id"), child_meta.get("previous_decision_revision")))
        parent_packet = lineage[index].get("packet", {})
        if (not bound or bound.get("type") != "Decision"
                or parent_packet.get("review_record_ref") != child_meta.get("previous_decision_id")):
            raise ValueError("continuation Decision binding does not match the previous task's saved judgment")
        decisions[index] = bound
    question_ids = set()
    for state in lineage:
        packet = state.get("packet", {})
        route_id = (packet.get("routes") or [None])[0]
        route = latest.get(route_id, {}) if route_id else {}
        route_question_id = route.get("research_question_id") or route.get("question_id")
        packet_question_id = packet.get("input", {}).get("research_question_id")
        if route_question_id and packet_question_id and route_question_id != packet_question_id:
            raise ValueError("TaskPacket question reference does not match its persisted Route")
        qid = route_question_id or packet_question_id
        if qid:
            question_ids.add(qid)
    if len(question_ids) > 1:
        raise ValueError("research continuation lineage crosses ResearchQuestions")
    for state in lineage:
        meta = state.get("packet", {}).get("input", {}).get("research_continuation")
        if not isinstance(meta, Mapping):
            continue
        if meta.get("question_id") and question_ids and meta["question_id"] not in question_ids:
            raise ValueError("continuation question binding does not match task lineage")
        previous = next((item for item in lineage if item.get("id") == meta.get("previous_task_id")), None)
        if previous is None or previous.get("revision") != meta.get("previous_task_revision"):
            raise ValueError("continuation references unavailable historical TaskState revision")
        previous_decision = versions.get((meta.get("previous_decision_id"), meta.get("previous_decision_revision")))
        decision_at_task_revision = task_decisions.get((previous.get("id"), previous.get("revision")))
        if (not previous_decision or previous_decision.get("type") != "Decision"
                or previous.get("packet", {}).get("review_record_ref") != meta.get("previous_decision_id")
                or not decision_at_task_revision
                or decision_at_task_revision.get("id") != previous_decision.get("id")
                or decision_at_task_revision.get("revision") != previous_decision.get("revision")):
            raise ValueError("continuation Decision binding does not match the previous task revision")
    final_state = lineage[-1]
    packet = final_state.get("packet", {})
    decision = decisions[-1]
    assets = {rid: rec for rid, rec in latest.items() if rec.get("type") == "Asset"}
    evidence = {rid: rec for rid, rec in latest.items() if rec.get("type") == "Evidence"}
    final_route = latest.get((packet.get("routes") or [None])[0], {})
    question_id = (final_route.get("research_question_id") or final_route.get("question_id")
                   or packet.get("input", {}).get("research_question_id") or packet.get("research_question_id"))
    question_rec = latest.get(question_id) if question_id else None
    question = (question_rec.get("statement") or question_rec.get("question") or question_rec.get("content")
                if question_rec else packet.get("question_statement") or packet.get("input", {}).get("review_question"))
    if not question:
        route = latest.get((packet.get("routes") or [None])[0], {})
        question = route.get("statement") or route.get("question_statement") or "当前记录未绑定研究问题文本"
    assessment = decision.get("assessment", {}) if decision else {}
    comparison = assessment.get("literature_comparison") if isinstance(assessment, Mapping) else None
    judgment = decision.get("judgment", {}) if decision else {}
    inherited = judgment.get("inherited_from", {}) if isinstance(judgment, Mapping) else {}
    inherited_decision = None
    if isinstance(inherited, Mapping) and isinstance(inherited.get("decision_id"), str):
        inherited_decision = versions.get((inherited["decision_id"], inherited.get("revision")))
        if inherited_decision is None or inherited_decision.get("type") != "Decision":
            raise ValueError("incremental judgment references unavailable historical Decision revision")
    inherited_source_decision = _source_decision_ancestor(inherited_decision, versions) if inherited_decision else None
    if comparison is None and inherited_source_decision:
        base_assessment = inherited_source_decision.get("assessment", {})
        comparison = base_assessment.get("literature_comparison") if isinstance(base_assessment, Mapping) else None
    summary = (judgment.get("summary") if inherited_decision else
               comparison.get("summary") if isinstance(comparison, Mapping) else
               assessment.get("parsed_note", {}).get("sections", {}).get("Summary") or
               judgment.get("summary") or assessment.get("note") or
               (decision.get("statement") if decision else None) or "尚未记录研究判断")
    lines = ["# 研究记录报告", "", f"**任务：** {_text(task_id)}  ·  **研究问题：** {_text(question)}", "",
             "> 这是已保存记录的派生阅读视图；未重新读取来源、刷新来源或核验科学结论。",
             "", "## 当前判断", "", f"**状态：** {_text(judgment.get('status') or (decision.get('status') if decision else 'PENDING'))}", "",
             _text(summary), ""]
    if decision:
        lines += [f"**Decision：** {_code_id(decision.get('id'))} r{decision.get('revision')}。", ""]
    if _decision_for_task(final_state, latest, task_decisions) is None:
        inherited_label = ("上方判断是继续研究前已完成并按版本绑定的历史判断。"
                           if decision else "当前仅显示任务问题和已绑定来源，尚无已记录判断。")
        lines += [f"**当前任务状态：** {_text(final_state.get('state'))}；尚未形成新判断。{inherited_label}", ""]
    if inherited_decision:
        base_judgment = inherited_decision.get("judgment", {})
        base_assessment = inherited_decision.get("assessment", {})
        base_summary = (base_assessment.get("literature_comparison", {}).get("summary")
                        if isinstance(base_assessment.get("literature_comparison"), Mapping) else
                        base_assessment.get("parsed_note", {}).get("sections", {}).get("Summary") or
                        base_judgment.get("summary"))
        lines += ["**继承的已完成判断（本次更新未替代其来源判读）：**", "",
                  f"{_code_id(inherited_decision.get('id'))} r{inherited_decision.get('revision')} · "
                  f"{_text(base_judgment.get('status'))} · {_text(base_summary)}", ""]
    if isinstance(comparison, Mapping):
        if inherited_decision and not assessment.get("literature_comparison"):
            lines += ["## 继承的来源比较", "", "以下比较来自绑定的历史判断，供本次增量记录参考。", ""]
        owner = decision if assessment.get("literature_comparison") else inherited_source_decision
        owner_assessment = owner.get("assessment", {}) if owner else {}
        pinned_assets, pinned_evidence = _pinned_sources(owner_assessment, versions)
        bindings = {b.get("asset_ref"): b for b in owner_assessment.get("source_bindings", [])
                    if isinstance(b, Mapping)}
        _render_comparison(lines, comparison, pinned_assets, pinned_evidence, bindings)
    else:
        sections = assessment.get("parsed_note", {}).get("sections", {})
        if not sections and isinstance(assessment.get("note"), str):
            active, buf = None, {}
            for line in assessment["note"].splitlines():
                if line.startswith("## "):
                    active = line[3:]; buf.setdefault(active, [])
                elif active:
                    buf[active].append(line)
            sections = {k: "\n".join(v).strip() for k, v in buf.items()}
        for name in ("Findings",):
            if sections.get(name):
                lines += [f"## {name}", "", _text(sections[name]), ""]
    source_owner = decision if assessment.get("source_bindings") else inherited_source_decision
    source_assessment = (source_owner.get("assessment", {}) if source_owner else
                         {"source_bindings": packet.get("input", {}).get("source_bindings", [])})
    source_pins, evidence_pins = _pinned_sources(source_assessment, versions)
    _render_bound_sources(lines, source_assessment, source_pins, evidence_pins)
    gaps = judgment.get("gaps", [])
    lines += ["## 缺口与适用范围", ""]
    for gap in gaps if isinstance(gaps, list) else [gaps]:
        lines.append(f"- {_text(gap)}")
    if not gaps:
        lines.append("- 当前记录未报告缺口")
    current_next = judgment.get("next_action", {}).get("action") if isinstance(judgment.get("next_action"), Mapping) else None
    lines += ["", "## 下一步建议", "", _text(current_next or
        (comparison.get("next") if isinstance(comparison, Mapping) else None) or
        "等待记录来源阅读或研究判断；由用户选择下一步。"), ""]

    if len(lineage) > 1:
        lines += ["## 研究过程与变化", ""]
        previous = None
        for state, saved_decision in zip(lineage, decisions):
            did = saved_decision.get("id") if saved_decision else None
            rev = saved_decision.get("revision") if saved_decision else None
            lines.append(f"- 任务 {_code_id(state['id'])}（TaskState r{state.get('revision')}），判断 {_code_id(did)} r{rev if rev else '?'}")
            if previous:
                old_sources, old_summary = _decision_sources(previous, versions)
                new_sources, new_summary = (_decision_sources(saved_decision, versions, old_sources)
                                            if saved_decision else ({}, None))
                old_ids, new_ids = set(old_sources), set(new_sources)
                lines.append(f"  - 来源变化（按文献身份）：新增 {', '.join(sorted(new_ids-old_ids)) or '无'}；"
                             f"移除 {', '.join(sorted(old_ids-new_ids)) or '无'}。")
                for identity in sorted(old_ids & new_ids):
                    before, after = old_sources[identity], new_sources[identity]
                    if before["asset_ref"] != after["asset_ref"]:
                        lines.append(f"  - {_text(identity)}：Asset 更换 {_code_id(before['asset_ref'])} → "
                                     f"{_code_id(after['asset_ref'])}，文献身份保持。")
                    if before["coverage"] != after["coverage"]:
                        lines.append(f"  - {identity}：覆盖从 {_text(before['coverage'])} 变为 {_text(after['coverage'])}。")
                    if before["evidence"] != after["evidence"]:
                        lines.append(f"  - {identity}：引用 Evidence IDs 从 {_text(before['evidence'])} 变为 "
                                     f"{_text(after['evidence'])}。")
                    if before["statuses"] != after["statuses"]:
                        lines.append(f"  - {identity}：记录状态从 {_text(before['statuses'])} 变为 "
                                     f"{_text(after['statuses'])}。")
                lines.append(f"  - 比较摘要：{_text(old_summary)} → {_text(new_summary)}。")
                meta = state.get("packet", {}).get("input", {}).get("research_continuation", {})
                lines.append(f"  - 继续原因：{_text(meta.get('reason') if isinstance(meta, Mapping) else None)}。")
            previous = saved_decision
        update = decision.get("update", {}) if decision else {}
        if isinstance(update, Mapping):
            lines += ["", f"本次记录变更字段：{_text(', '.join(update.get('changed_fields', [])) or '未报告')}。"]
    return "\n".join(lines).rstrip() + "\n"
