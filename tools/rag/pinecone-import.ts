import {
  Errors,
  Pinecone,
  type IndexModel,
  type RecordMetadata,
} from "@pinecone-database/pinecone";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { z } from "zod";
import {
  preparePineconeImport,
  type PineconeStandardRecord,
} from "./standard-records.ts";

const BATCH_SIZE = 96;
const MAX_BATCH_ATTEMPTS = 5;
const RETRY_BASE_DELAY_MS = 1_000;
const DEFAULT_EMBED_MODEL = "multilingual-e5-large";
const DEFAULT_TEXT_FIELD = "chunk_text";

const optionalValue = z.preprocess(
  (value) => (value === "" ? undefined : value),
  z.string().trim().min(1).optional(),
);
const reservedRecordFields = new Set([
  "_id",
  "evidence_kind",
  "standard_name",
  "standard_version",
  "clause",
  "source_location",
  "applicability",
  "effective_status",
  "standard_code",
  "source_category",
  "source_name",
  "registry_relevance",
]);
const textFieldSchema = z
  .string()
  .trim()
  .min(1)
  .max(128)
  .refine((value) => !reservedRecordFields.has(value));

const importConfigSchema = z.object({
  PINECONE_API_KEY: z.string().trim().min(1),
  PINECONE_INDEX: z
    .string()
    .trim()
    .regex(/^[a-z0-9](?:[a-z0-9-]{0,43}[a-z0-9])?$/),
  PINECONE_NAMESPACE: optionalValue,
  PINECONE_CLOUD: optionalValue,
  PINECONE_REGION: optionalValue,
  PINECONE_EMBED_MODEL: z
    .string()
    .trim()
    .min(1)
    .default(DEFAULT_EMBED_MODEL),
  PINECONE_TEXT_FIELD: textFieldSchema.default(DEFAULT_TEXT_FIELD),
});

type ImportConfig = z.output<typeof importConfigSchema>;
type PineconeMappedRecord = { _id: string } & RecordMetadata;
type UpsertRecordsTarget = {
  upsertRecords(options: { records: PineconeMappedRecord[] }): Promise<void>;
};
type BatchRetryOptions = {
  maxAttempts?: number;
  baseDelayMs?: number;
  sleep?: (delayMs: number) => Promise<void>;
  onRetry?: (attempt: number, delayMs: number) => void;
};

class ImportConfigurationError extends Error {}

function isRetryablePineconeError(error: unknown): boolean {
  return (
    error instanceof Errors.PineconeConnectionError ||
    error instanceof Errors.PineconeRequestError ||
    error instanceof Errors.PineconeInternalServerError ||
    error instanceof Errors.PineconeUnavailableError ||
    error instanceof Errors.PineconeMaxRetriesExceededError ||
    error instanceof Errors.PineconeTimeoutError ||
    error instanceof Errors.PineconeUnmappedHttpError
  );
}

async function sleep(delayMs: number): Promise<void> {
  await new Promise((resolveDelay) => setTimeout(resolveDelay, delayMs));
}

export async function upsertBatchWithRetry(
  index: UpsertRecordsTarget,
  records: PineconeMappedRecord[],
  options: BatchRetryOptions = {},
): Promise<void> {
  const maxAttempts = options.maxAttempts ?? MAX_BATCH_ATTEMPTS;
  const baseDelayMs = options.baseDelayMs ?? RETRY_BASE_DELAY_MS;
  const sleepImpl = options.sleep ?? sleep;
  const onRetry =
    options.onRetry ??
    ((attempt: number, delayMs: number) => {
      console.warn(
        `Pinecone 批次写入失败，${delayMs}ms 后进行第 ${attempt + 1}/${maxAttempts} 次尝试。`,
      );
    });

  if (
    !Number.isInteger(maxAttempts) ||
    maxAttempts < 1 ||
    maxAttempts > 10 ||
    !Number.isFinite(baseDelayMs) ||
    baseDelayMs < 0
  ) {
    throw new ImportConfigurationError("Pinecone 批次重试配置不合法。");
  }
  if (records.length === 0) return;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      await index.upsertRecords({ records });
      return;
    } catch (error) {
      if (
        attempt === maxAttempts ||
        !isRetryablePineconeError(error)
      ) {
        throw error;
      }
      const delayMs = baseDelayMs * 2 ** (attempt - 1);
      onRetry(attempt, delayMs);
      await sleepImpl(delayMs);
    }
  }
}

function hasParameter(
  parameters: object | null | undefined,
  name: string,
  expected: string,
): boolean {
  return (
    parameters !== null &&
    parameters !== undefined &&
    (parameters as Record<string, unknown>)[name] === expected
  );
}

function hasSupportedTruncation(
  parameters: object | null | undefined,
): boolean {
  return (
    hasParameter(parameters, "truncate", "NONE") ||
    hasParameter(parameters, "truncate", "END")
  );
}

function parseArguments(argv: string[]): {
  execute: boolean;
  createIndex: boolean;
} {
  const known = new Set(["--execute", "--create-index"]);
  const unknown = argv.filter((argument) => !known.has(argument));
  if (unknown.length > 0) {
    throw new ImportConfigurationError(`不支持的参数：${unknown.join(", ")}`);
  }
  const execute = argv.includes("--execute");
  const createIndex = argv.includes("--create-index");
  if (createIndex && !execute) {
    throw new ImportConfigurationError(
      "--create-index 只能与 --execute 一起使用。",
    );
  }
  return { execute, createIndex };
}

function readImportConfig(createIndex: boolean): ImportConfig {
  const parsed = importConfigSchema.safeParse(process.env);
  if (!parsed.success) {
    throw new ImportConfigurationError(
      "Pinecone 配置缺失或不合法，请检查 .env.local。",
    );
  }
  if (
    createIndex &&
    (!parsed.data.PINECONE_CLOUD || !parsed.data.PINECONE_REGION)
  ) {
    throw new ImportConfigurationError(
      "创建索引前必须配置 PINECONE_CLOUD 和 PINECONE_REGION。",
    );
  }
  return parsed.data;
}

export function assertIntegratedIndexCompatible(
  index: IndexModel,
  expectedModel: string,
  expectedTextField = DEFAULT_TEXT_FIELD,
): void {
  const parsedTextField = textFieldSchema.safeParse(expectedTextField);
  if (!parsedTextField.success) {
    throw new ImportConfigurationError(
      "Pinecone integrated embedding 文本字段配置不合法。",
    );
  }
  const textField = index.schema.fields[parsedTextField.data];
  if (
    !textField ||
    !("type" in textField) ||
    textField.type !== "semantic_text" ||
    textField.model !== expectedModel ||
    !hasParameter(textField.writeParameters, "input_type", "passage") ||
    !hasParameter(textField.readParameters, "input_type", "query") ||
    !hasSupportedTruncation(textField.writeParameters) ||
    !hasSupportedTruncation(textField.readParameters)
  ) {
    throw new ImportConfigurationError(
      `索引必须使用 ${expectedModel}，并将 integrated embedding 文本字段配置为 ${parsedTextField.data}。`,
    );
  }
  if (!index.status.ready) {
    throw new ImportConfigurationError("Pinecone 索引尚未就绪。");
  }
}

async function resolveIndex(
  client: Pinecone,
  config: ImportConfig,
  createIndex: boolean,
): Promise<IndexModel> {
  let index: IndexModel;
  try {
    index = await client.indexes.describe(config.PINECONE_INDEX);
  } catch (error) {
    if (!(error instanceof Errors.PineconeNotFoundError)) {
      throw error;
    }
    if (!createIndex) {
      throw new ImportConfigurationError(
        "Pinecone 索引不存在；确认配置后使用 --create-index 显式创建。",
      );
    }
    index = await client.indexes.createForModel({
      name: config.PINECONE_INDEX,
      cloud: config.PINECONE_CLOUD!,
      region: config.PINECONE_REGION!,
      embed: {
        model: config.PINECONE_EMBED_MODEL,
        fieldMap: { text: config.PINECONE_TEXT_FIELD },
        writeParameters: {
          input_type: "passage",
          truncate: "NONE",
        },
        readParameters: {
          input_type: "query",
          truncate: "NONE",
        },
      },
      deletionProtection: "enabled",
      waitUntilReady: true,
      timeout: 10 * 60 * 1_000,
    });
  }
  assertIntegratedIndexCompatible(
    index,
    config.PINECONE_EMBED_MODEL,
    config.PINECONE_TEXT_FIELD,
  );
  return index;
}

export function mapRecordsForPinecone(
  records: PineconeStandardRecord[],
  textField = DEFAULT_TEXT_FIELD,
): PineconeMappedRecord[] {
  const parsedTextField = textFieldSchema.parse(textField);
  return records.map(({ _id, chunk_text, ...metadata }) => ({
    _id,
    [parsedTextField]: chunk_text,
    ...metadata,
  }));
}

async function uploadRecords(
  client: Pinecone,
  config: ImportConfig,
  records: PineconeStandardRecord[],
): Promise<void> {
  const index = client.index({
    name: config.PINECONE_INDEX,
    ...(config.PINECONE_NAMESPACE
      ? { namespace: config.PINECONE_NAMESPACE }
      : {}),
  });
  const pineconeRecords = mapRecordsForPinecone(
    records,
    config.PINECONE_TEXT_FIELD,
  );

  for (let start = 0; start < pineconeRecords.length; start += BATCH_SIZE) {
    const batch = pineconeRecords.slice(start, start + BATCH_SIZE);
    await upsertBatchWithRetry(index, batch);
    const completed = Math.min(start + batch.length, pineconeRecords.length);
    console.log(`Pinecone 已写入 ${completed}/${pineconeRecords.length}`);
  }
}

async function main(): Promise<void> {
  const arguments_ = parseArguments(process.argv.slice(2));
  const prepared = preparePineconeImport();

  console.log(`候选条文：${prepared.report.counts.selected_records}`);
  console.log(`导入记录：${prepared.recordsPath}`);
  console.log(`审计报告：${prepared.reportPath}`);

  if (!arguments_.execute) {
    console.log(
      prepared.report.ready_for_upload
        ? "Dry-run 通过；使用 npm run rag:import 执行真实上传。"
        : `Dry-run 未通过：${prepared.report.blockers.join("；")}`,
    );
    return;
  }

  if (!prepared.report.ready_for_upload) {
    throw new ImportConfigurationError(
      `导入门禁未通过：${prepared.report.blockers.join("；")}`,
    );
  }

  const config = readImportConfig(arguments_.createIndex);
  const client = new Pinecone({ apiKey: config.PINECONE_API_KEY });
  await resolveIndex(client, config, arguments_.createIndex);
  await uploadRecords(client, config, prepared.records);
  console.log(
    `Pinecone 导入完成：index=${config.PINECONE_INDEX}，namespace=${config.PINECONE_NAMESPACE ?? "(default)"}`,
  );
}

const isDirectExecution =
  process.argv[1] !== undefined &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href;

if (isDirectExecution) {
  main().catch((error: unknown) => {
    if (error instanceof ImportConfigurationError) {
      console.error(error.message);
    } else {
      console.error(
        "Pinecone 导入失败；未输出远端响应正文，请检查配置、配额和网络。",
      );
    }
    process.exitCode = 1;
  });
}
