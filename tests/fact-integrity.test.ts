import { describe, expect, it } from 'vitest';
import { canonicalDigest, prepareAgentPayload, verifyEngineSnapshot } from '@/server/preparation/fact-integrity';
import { executeAgentRun } from '@/server/agents/executor';

const input = () => ({ schema: 'excavaguard.daily_report_input/v1', project: { supporting_context: { documents: [], notice: '未提供巡视记录' } }, items: [{ cumulative: 7 }] });
describe('三Agent事实交接边界', () => {
  it('冻结内容优先，重复传入相同辅助资料兼容，替换资料拒绝', () => {
    const p = input();
    expect(prepareAgentPayload(p, structuredClone(p.project.supporting_context))).toEqual(p);
    expect(() => prepareAgentPayload(p, { documents: [], notice: '巡视正常' })).toThrow('辅助资料与冻结事实不一致');
  });
  it('克隆切断调用方引用；规范化散列不受键顺序影响', () => {
    const p = input(); const copied = prepareAgentPayload(p) as typeof p;
    p.items[0].cumulative = 0;
    expect(copied.items[0].cumulative).toBe(7);
    expect(canonicalDigest({ a: 1, b: 2 })).toBe(canonicalDigest({ b: 2, a: 1 }));
  });
  it('旧格式运行也要检查续跑事实指纹', () => {
    const payload = input(); const snapshot = { ref: { content_hash: canonicalDigest(payload) }, payload };
    verifyEngineSnapshot(snapshot); payload.items[0].cumulative = 0;
    expect(() => verifyEngineSnapshot(snapshot)).toThrow('保存的指纹不一致');
  });
  it('损坏的续跑检查点在任何模型、渲染或保存前被拒绝', async () => {
    let saved: Parameters<typeof executeAgentRun>[0]['initialState'];
    await expect(executeAgentRun({ enginePayload: input() }, { checkpoint: async ({ state }) => { saved = state; throw new Error('interrupt'); } })).rejects.toThrow('interrupt');
    (saved!.engine_snapshot.payload as ReturnType<typeof input>).items[0].cumulative = 0;
    let touched = false;
    await expect(executeAgentRun({ enginePayload: null, initialState: saved }, { checkpoint: async () => { touched = true; } })).rejects.toThrow('保存的指纹不一致');
    expect(touched).toBe(false);
  });
  it('续跑不能替换输入、辅助资料或辅助检查点', async () => {
    let saved: Parameters<typeof executeAgentRun>[0]['initialState'];
    await expect(executeAgentRun({ enginePayload: input() }, { checkpoint: async ({ state }) => { saved = state; throw new Error('interrupt'); } })).rejects.toThrow('interrupt');
    const changed = input(); changed.items[0].cumulative = 0;
    await expect(executeAgentRun({ enginePayload: changed, initialState: saved })).rejects.toThrow('续跑输入');
    await expect(executeAgentRun({ enginePayload: null, initialState: saved, supportingContext: { documents: [] } })).rejects.toThrow('辅助资料与冻结事实不一致');
    saved!.context_snapshot = { ref: { ...saved!.engine_snapshot.ref, schema: 'excavaguard.supporting_context/v1' }, payload: { documents: [] } };
    await expect(executeAgentRun({ enginePayload: null, initialState: saved })).rejects.toThrow('辅助资料检查点');
  });
  it('检查点回调不能改变执行器中的冻结事实，辅助资料由载荷自动恢复', async () => {
    const p = input(); let seenContext = false;
    await expect(executeAgentRun({ enginePayload: p }, { checkpoint: async ({ state, steps }) => {
      if (steps === 1 && !state.context_snapshot) { (state.engine_snapshot.payload as typeof p).items[0].cumulative = 0; }
      if (state.context_snapshot) { seenContext = true; expect((state.engine_snapshot.payload as typeof p).items[0].cumulative).toBe(7); throw new Error('context restored'); }
    }, render: async () => { throw new Error('stop'); } })).rejects.toThrow('context restored');
    expect(seenContext).toBe(true); expect(p.items[0].cumulative).toBe(7);
  });
});
