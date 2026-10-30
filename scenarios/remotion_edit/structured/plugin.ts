/** Scene policy only; matching, DSH lifecycle and verified receipts remain shared. */
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {installOnlineMotif} from '../../../src/adapters/dsh_online_motif.mjs';
export const name = 'remotion-certified-source-dereference';
export const inject = ['llm', 'agents'];
export function apply(ctx) {
  const path = process.env.SSS_ONLINE_MOTIF_MANIFEST;
  if (!path) return;
  const manifest = JSON.parse(readFileSync(path, 'utf8'));
  const lockFiles = ['scenarios/remotion_edit/structured/server.py',
    'scenarios/remotion_edit/server.py', 'scenarios/remotion_edit/structured/contracts.json',
    'src/adapters/dsh_online_motif.mjs', 'src/motif_core/online_skill_runtime.mjs',
    'src/motif_core/source_dereference.generated.mjs', 'package-lock.json'];
  if (JSON.stringify(Object.keys(manifest.scene_code_locks ?? {}).sort()) !==
      JSON.stringify([...lockFiles].sort())) throw Error('scene code locks missing');
  for (const file of lockFiles) {
    const data = readFileSync(new URL('../../../' + file, import.meta.url));
    if (createHash('sha256').update(data).digest('hex') !== manifest.scene_code_locks[file]) {
      throw Error('certified scene implementation changed: ' + file);
    }
  }
  for (const file of ['package-lock.json', 'node_modules/@remotion/compositor-linux-x64-gnu/ffprobe']) {
    const data = readFileSync(new URL('../../../../runtime/' + file, import.meta.url));
    if (createHash('sha256').update(data).digest('hex') !== manifest.scene_runtime_locks?.[file]) {
      throw Error('certified media dependency changed');
    }
  }
  if (process.env.SSS_REMOTION_IMAGE !== manifest.scene_image) throw Error('render image identity changed');
  if (!manifest.artifacts?.length || manifest.artifacts.some(a =>
    a.tools.length !== 2 || a.tools[0] !== 'mcp__remotion__pin_asset' ||
    a.tools[1] !== 'mcp__remotion__probe_media' ||
    manifest.contracts[a.tools[1]]?.source_dereference !== true)) {
    throw Error('scene accepts only independently certified pin/read edges');
  }
  installOnlineMotif(ctx, {
    // A closed dereference has no remaining semantic choice. Unexpected
    // semantic paths fail closed in the shared interceptor, never score 1.0.
    similarity: async () => {throw Error('semantic matching disabled in closed-read experiment');},
  });
}
