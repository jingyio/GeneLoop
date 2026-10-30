/** Native source-form storage reuses F02's authoritative update validation. */
import {readFileSync} from 'node:fs';
import {bytesSha256,decodeRsiRecord,validateRsiUpdate} from '../src/adapters/rsi_protocol.ts';
const input=JSON.parse(readFileSync(0,'utf8'));
const candidate=decodeRsiRecord(input.candidate),report=decodeRsiRecord(input.report);
const host={versions:input.versions,candidateSha256:candidate.sha256,payloadSha256:input.payload_sha256,
 reportSha256:report.sha256,approvedReports:new Map([[report.record.payload.id,report.sha256]]),
 evidence:new Map(input.evidence.map(r=>[r.payload.id,r])),diagnoses:new Map(input.diagnoses.map(r=>[r.payload.id,r]))};
const plan=validateRsiUpdate(input.candidate,input.report,host);
process.stdout.write(JSON.stringify({...plan,candidate_sha256:bytesSha256(input.candidate),report_sha256:bytesSha256(input.report)}));
