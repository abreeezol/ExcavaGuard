"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { EngineeringSetup } from "@/contracts/project-setup";

export type { EngineeringSetup };

export type NewProjectInput = {
  name: string;
  engineering_type: string;
};

export function NewProjectDialog({
  setups,
  busy,
  error,
  onClose,
  onCreate,
}: {
  setups: EngineeringSetup[];
  busy: boolean;
  error?: string;
  onClose: () => void;
  onCreate: (input: NewProjectInput) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [engineeringType, setEngineeringType] = useState<string>(setups[0]?.id ?? "");

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialog.current;
    node?.showModal();
    return () => {
      node?.close();
      previousFocus?.focus();
    };
  }, []);

  return <dialog
    ref={dialog}
    className="wb-range-dialog wb-project-dialog"
    aria-labelledby="new-project-title"
    onCancel={event => {
      event.preventDefault();
      if (!busy) onClose();
    }}
  >
    <form onSubmit={event => {
      event.preventDefault();
      if (!busy && name.trim() && engineeringType) {
        onCreate({ name: name.trim(), engineering_type: engineeringType });
      }
    }}>
      <div className="wb-dialog-head">
        <div>
          <p className="eyebrow">工作台启动</p>
          <h2 id="new-project-title">新建工程</h2>
        </div>
        <button
          type="button"
          className="wb-btn wb-icon-btn"
          aria-label="关闭新建工程"
          title="关闭"
          disabled={busy}
          onClick={onClose}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>

      {error && <div role="alert" className="wb-alert wb-alert-error">{error}</div>}
      <div className="wb-dialog-stage">
        <p className="wb-hint">创建后进入分析准备，继续填写工程条件并上传监测数据。</p>
        <label className="wb-field">
          <span>工程类型</span>
          <select
            autoFocus
            value={engineeringType}
            onChange={event => setEngineeringType(event.target.value)}
          >
            {setups.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="wb-field">
          <span>工程名称</span>
          <input
            required
            maxLength={100}
            value={name}
            onChange={event => setName(event.target.value)}
            placeholder="例如：杭州一期基坑工程"
          />
        </label>
      </div>

      <div className="wb-dialog-actions">
        <button type="button" className="wb-btn" disabled={busy} onClick={onClose}>取消</button>
        <button className="wb-btn wb-btn-primary" disabled={busy || !name.trim() || !engineeringType}>
          {busy ? "正在创建…" : "创建工程"}
        </button>
      </div>
    </form>
  </dialog>;
}
