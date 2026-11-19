import { it, expect } from 'vitest';
import { validateNarrativeGrounding } from '@/server/agents/report-model';
const p=(text='请工程师复核。')=>({text,evidence_ids:[]});
const narrative=(text:string,appendix='本表为当日观测明细。')=>({work_condition:p(),analysis:[p(text)],recommendations:[p()],limitations:[p()],appendix_analysis:[{form:'S',analysis:p(appendix),recommendation:p()}]});
const facts={'project.pre_agent_preparation.facts.report_kind':'daily','summary.overall_risk_level':'预警','summary.abstain.REVERSE_DIRECTION_CONTROL_NOT_PROVIDED':576};
it('工程师指出的弃权计数不能当原因',()=>{expect(()=>validateNarrativeGrounding(narrative('未知原因为{{fact:summary.abstain.REVERSE_DIRECTION_CONTROL_NOT_PROVIDED}}。'),facts,[],['S'])).toThrow('COUNT_AS_ABSTAIN_REASON');});
it('整体风险等级不能解释为条目数量',()=>{expect(()=>validateNarrativeGrounding(narrative('整体预警等级为{{fact:summary.overall_risk_level}}，该字段表示条目数量统计而非等级名称。'),facts,[],['S'])).toThrow('RISK_LEVEL_AS_COUNT');});
it('日报不得错误套用周期代表值口径',()=>{expect(()=>validateNarrativeGrounding(narrative('请核对。','本表汇总各通道周期最严重原观测。'),facts,[],['S'])).toThrow('DAILY_PERIOD_CONFUSION');expect(()=>validateNarrativeGrounding(narrative('请核对。','本表汇总各通道周期最严重原观测。'),{...facts,'project.pre_agent_preparation.facts.report_kind':'weekly'},[],['S'])).not.toThrow();});
