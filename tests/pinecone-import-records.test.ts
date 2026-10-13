import { describe, expect, it, vi } from "vitest";
import {
  Errors,
  type IndexModel,
} from "@pinecone-database/pinecone";
import {
  assertIntegratedIndexCompatible,
  mapRecordsForPinecone,
  upsertBatchWithRetry,
} from "../tools/rag/pinecone-import";
import {
  buildPineconeStandardRecords,
  readChunksJsonl,
  readRegistry,
  readStatusManifest,
  type RegistryStandard,
  type SourceChunk,
  type StandardStatusManifest,
} from "../tools/rag/standard-records";

const registry: RegistryStandard[] = [
  {
    code: "DEMO-2026",
    name: "测试规范",
    file_name: "DEMO-2026 测试规范.pdf",
    category: "测试类",
    relevance: "primary",
    scope_note: "仅用于自动化测试",
  },
];

const activeManifest: StandardStatusManifest = {
  schema_version: "excavaguard.standard_status/v1",
  reviewed_at: "2026-10-13T10:00:00+08:00",
  reviewed_by: "自动化测试",
  standards: {
    "DEMO-2026": {
      effective_status: "active",
    },
  },
};

const validChunk: SourceChunk = {
  id: "chunk-1",
  content: "8.0.1 仅用于自动化测试的条文内容。",
  source: "DEMO-2026 测试规范",
  category: "测试类",
  clause: "8.0.1",
};

describe("Pinecone 规范导入记录", () => {
  it("从条文切片和规范索引生成完整的可追溯元数据", () => {
    const result = buildPineconeStandardRecords({
      chunks: [validChunk],
      registry,
      statusManifest: activeManifest,
      generatedAt: "2026-10-13T02:00:00.000Z",
    });

    expect(result.report.ready_for_upload).toBe(true);
    expect(result.records).toEqual([
      {
        _id: "chunk-1",
        chunk_text: "8.0.1 仅用于自动化测试的条文内容。",
        evidence_kind: "standard",
        standard_name: "测试规范",
        standard_version: "DEMO-2026",
        clause: "8.0.1",
        source_location:
          "data/ocr_text/测试类/DEMO-2026 测试规范.txt#chunk=chunk-1",
        applicability: ["仅用于自动化测试"],
        effective_status: "active",
        standard_code: "DEMO-2026",
        source_category: "测试类",
        source_name: "DEMO-2026 测试规范",
        registry_relevance: "primary",
      },
    ]);
    const [{ chunk_text, ...metadata }] = result.records;
    expect(mapRecordsForPinecone(result.records, "text")).toEqual([
      { ...metadata, text: chunk_text },
    ]);
  });

  it("排除项目文件和无条文号切片，不为其补造元数据", () => {
    const result = buildPineconeStandardRecords({
      chunks: [
        validChunk,
        { ...validChunk, id: "blank", clause: "" },
        {
          ...validChunk,
          id: "project",
          category: "项目文件",
          source: "项目内部细则",
        },
        {
          ...validChunk,
          id: "oversized",
          content: "测".repeat(421),
        },
      ],
      registry,
      statusManifest: activeManifest,
    });

    expect(result.records).toHaveLength(1);
    expect(result.report.counts).toMatchObject({
      selected_records: 1,
      excluded_project_records: 1,
      excluded_missing_clause_records: 1,
      excluded_oversized_records: 1,
    });
    expect(result.report.oversized_record_ids).toEqual(["oversized"]);
  });

  it("重复规范只使用人工指定的 OCR 来源", () => {
    const duplicateRegistry: RegistryStandard[] = [
      registry[0],
      {
        ...registry[0],
        file_name: "DEMO-2026 测试规范副本.pdf",
        category: "副本类",
      },
    ];
    const manifest: StandardStatusManifest = {
      ...activeManifest,
      standards: {
        "DEMO-2026": {
          effective_status: "active",
          preferred_category: "测试类",
        },
      },
    };
    const result = buildPineconeStandardRecords({
      chunks: [
        validChunk,
        {
          ...validChunk,
          id: "chunk-copy",
          category: "副本类",
          source: "DEMO-2026 测试规范副本",
        },
      ],
      registry: duplicateRegistry,
      statusManifest: manifest,
    });

    expect(result.records.map((record) => record._id)).toEqual(["chunk-1"]);
    expect(
      result.report.counts.excluded_non_preferred_source_records,
    ).toBe(1);
    expect(result.report.duplicate_standard_sources).toEqual([
      {
        standard_code: "DEMO-2026",
        available_categories: ["测试类", "副本类"],
        preferred_category: "测试类",
      },
    ]);
  });

  it("状态未知时生成审计清单但阻止真实上传", () => {
    const result = buildPineconeStandardRecords({
      chunks: [validChunk],
      registry,
      statusManifest: {
        ...activeManifest,
        reviewed_at: null,
        reviewed_by: null,
        standards: {
          "DEMO-2026": {
            effective_status: "unknown",
          },
        },
      },
    });

    expect(result.records[0].effective_status).toBe("unknown");
    expect(result.report.ready_for_upload).toBe(false);
    expect(result.report.unknown_status_codes).toEqual(["DEMO-2026"]);
    expect(result.report.blockers).toContain(
      "仍有规范的生效状态为 unknown 或未登记。",
    );
  });

  it("拒绝模型、文本字段或就绪状态不匹配的在线索引", () => {
    const compatible = {
      schema: {
        fields: {
          chunk_text: {
            type: "semantic_text",
            model: "multilingual-e5-large",
            writeParameters: {
              input_type: "passage",
              truncate: "NONE",
            },
            readParameters: {
              input_type: "query",
              truncate: "NONE",
            },
          },
        },
      },
      status: { ready: true },
    } as unknown as IndexModel;

    expect(() =>
      assertIntegratedIndexCompatible(compatible, "multilingual-e5-large"),
    ).not.toThrow();
    const configuredNvidiaIndex = {
      ...compatible,
      schema: {
        fields: {
          text: {
            type: "semantic_text",
            model: "llama-text-embed-v2",
            writeParameters: {
              input_type: "passage",
              truncate: "END",
            },
            readParameters: {
              input_type: "query",
              truncate: "END",
            },
          },
        },
      },
    } as unknown as IndexModel;
    expect(() =>
      assertIntegratedIndexCompatible(
        configuredNvidiaIndex,
        "llama-text-embed-v2",
        "text",
      ),
    ).not.toThrow();
    expect(() =>
      assertIntegratedIndexCompatible(
        {
          ...compatible,
          schema: {
            fields: {
              chunk_text: {
                type: "semantic_text",
                model: "other-model",
              },
            },
          },
        } as unknown as IndexModel,
        "multilingual-e5-large",
      ),
    ).toThrow("索引必须使用 multilingual-e5-large");
    expect(() =>
      assertIntegratedIndexCompatible(
        {
          ...compatible,
          status: { ready: false },
        } as unknown as IndexModel,
        "multilingual-e5-large",
      ),
    ).toThrow("Pinecone 索引尚未就绪。");
  });

  it("瞬时写入失败按指数退避重试，鉴权失败立即停止", async () => {
    const records = mapRecordsForPinecone(
      buildPineconeStandardRecords({
        chunks: [validChunk],
        registry,
        statusManifest: activeManifest,
      }).records,
      "text",
    );
    const retryingUpsert = vi
      .fn()
      .mockRejectedValueOnce(
        new Errors.PineconeConnectionError(new Error("temporary-1")),
      )
      .mockRejectedValueOnce(
        new Errors.PineconeConnectionError(new Error("temporary-2")),
      )
      .mockResolvedValue(undefined);
    const delays: number[] = [];
    const retries: Array<[number, number]> = [];

    await upsertBatchWithRetry(
      { upsertRecords: retryingUpsert },
      records,
      {
        maxAttempts: 3,
        baseDelayMs: 5,
        sleep: async (delayMs) => {
          delays.push(delayMs);
        },
        onRetry: (attempt, delayMs) => {
          retries.push([attempt, delayMs]);
        },
      },
    );

    expect(retryingUpsert).toHaveBeenCalledTimes(3);
    expect(delays).toEqual([5, 10]);
    expect(retries).toEqual([
      [1, 5],
      [2, 10],
    ]);

    const authorizationError = new Errors.PineconeAuthorizationError({
      status: 401,
    });
    const rejectedUpsert = vi.fn().mockRejectedValue(authorizationError);
    await expect(
      upsertBatchWithRetry(
        { upsertRecords: rejectedUpsert },
        records,
        {
          maxAttempts: 3,
          sleep: async () => undefined,
          onRetry: () => undefined,
        },
      ),
    ).rejects.toBe(authorizationError);
    expect(rejectedUpsert).toHaveBeenCalledTimes(1);
  });

  it("当前知识资产生成 7,180 条已复核候选记录", () => {
    const chunks = readChunksJsonl("data/chunks.jsonl");
    const standards = readRegistry(
      "确定性计算层/standards/default/规范库索引.json",
    );
    const statusManifest = readStatusManifest("rag/standard-status.json");
    const result = buildPineconeStandardRecords({
      chunks,
      registry: standards,
      statusManifest,
    });

    expect(result.report.counts).toMatchObject({
      input_rows: 8_703,
      registry_standard_codes: 29,
      selected_records: 7_180,
      excluded_project_records: 16,
      excluded_non_preferred_source_records: 108,
      excluded_missing_clause_records: 1_375,
      excluded_oversized_records: 24,
      duplicate_record_ids: 0,
      records_by_effective_status: {
        active: 7_180,
        inactive: 0,
        unknown: 0,
      },
    });
    expect(result.report.unmatched_sources).toEqual([]);
    expect(result.report.conflicting_record_ids).toEqual([]);
    expect(result.report.oversized_record_ids).toHaveLength(24);
    expect(result.report.ready_for_upload).toBe(true);
  });
});
