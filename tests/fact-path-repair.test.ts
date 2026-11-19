import { expect, it } from 'vitest';
import { normalizeNarrativeFactPaths, validateNarrativeGrounding } from '@/server/agents/report-model';
import type { ReportNarrative } from '@/contracts/ai-report';
const paragraph = (text = '请工程师复核。') => ({ text, evidence_ids: [] as string[] });
function narrative(text: string): ReportNarrative {
  return { work_condition: paragraph(), analysis: [paragraph(text)], recommendations: [paragraph()], limitations: [paragraph()], appendix_analysis: [] };
}
const facts = { 'items.1008.point_id': 'SIM-01', 'items.1008.current': 26 };
it('only repairs unambiguous existing array paths and records each repair', () => {
  const input = narrative('测点{{fact:items:1008.point_id}}当前值{{fact:items[1008].current}}。');
  const result = normalizeNarrativeFactPaths(input, facts);
  expect(result.repairs).toHaveLength(2);
  expect(result.narrative.analysis[0].text).toBe('测点{{fact:items.1008.point_id}}当前值{{fact:items.1008.current}}。');
  expect(input.analysis[0].text).toContain('items:1008');
  expect(() => validateNarrativeGrounding(result.narrative, facts, [], [])).not.toThrow();
});
it.each(['{{fact:items:1009.point_id}}', '{{fact:items[1008].nonexistent}}', '数值为26。'])(
  'keeps rejecting unknown paths and unsupported numbers: %s', text => {
    const result = normalizeNarrativeFactPaths(narrative(text), facts);
    expect(result.repairs).toEqual([]);
    expect(() => validateNarrativeGrounding(result.narrative, facts, [], [])).toThrow('UNGROUNDED_FACT');
  });
