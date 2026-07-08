import { Collapse, Divider, Input, InputNumber, Select, Space, Switch, Typography } from 'antd'
import { useState } from 'react'
import type { BuilderAdvancedOptions } from '../api/profileBuilder'

type CompletionType = 'ui_tree_stable' | 'pixel_stable' | 'fixed_delay'
type Method = 'ui_tree_only' | 'ocr_only' | 'ui_tree_then_ocr'

interface VlmForm {
  base_url: string
  model: string
  api_key: string
}

interface Props {
  onChange: (advanced: BuilderAdvancedOptions) => void
}

/**
 * Optional overrides applied to the generated draft, exposing schema
 * capabilities the guided capture can't infer: completion detection type,
 * extraction method, VLM extraction (copy_button_vlm / response_vlm), and a
 * device init playbook. Emits a BuilderAdvancedOptions patch on any change;
 * fields left at their defaults are omitted so the rule-derived draft wins.
 */
export function BuilderAdvancedPanel({ onChange }: Props) {
  // "" = don't override (keep the rule-derived value).
  const [completion, setCompletion] = useState<'' | CompletionType>('')
  const [stableSec, setStableSec] = useState(2)
  const [maxWaitSec, setMaxWaitSec] = useState(180)
  const [waitSec, setWaitSec] = useState(8)
  const [method, setMethod] = useState<'' | Method>('')
  const [copyVlm, setCopyVlm] = useState<VlmForm>({ base_url: '', model: '', api_key: '' })
  const [copyVlmOn, setCopyVlmOn] = useState(false)
  const [respVlm, setRespVlm] = useState<VlmForm & { response_hint: string }>({
    base_url: '',
    model: '',
    api_key: '',
    response_hint: '',
  })
  const [respVlmOn, setRespVlmOn] = useState(false)
  const [initReboot, setInitReboot] = useState(false)
  const [initRebootTouched, setInitRebootTouched] = useState(false)
  const [initActionText, setInitActionText] = useState('')

  // Recompute the full patch from a merged snapshot on any change (the
  // individual setters lag a render, so callers pass the new value in).
  const buildAndEmit = (next: {
    completion?: '' | CompletionType
    stableSec?: number
    maxWaitSec?: number
    waitSec?: number
    method?: '' | Method
    copyVlmOn?: boolean
    copyVlm?: VlmForm
    respVlmOn?: boolean
    respVlm?: VlmForm & { response_hint: string }
    initReboot?: boolean
    initRebootTouched?: boolean
    initActionText?: string
  }) => {
    const c = next.completion ?? completion
    const ss = next.stableSec ?? stableSec
    const mw = next.maxWaitSec ?? maxWaitSec
    const ws = next.waitSec ?? waitSec
    const m = next.method ?? method
    const cvOn = next.copyVlmOn ?? copyVlmOn
    const cv = next.copyVlm ?? copyVlm
    const rvOn = next.respVlmOn ?? respVlmOn
    const rv = next.respVlm ?? respVlm
    const ir = next.initReboot ?? initReboot
    const irT = next.initRebootTouched ?? initRebootTouched
    const iaText = next.initActionText ?? initActionText

    const adv: BuilderAdvancedOptions = {}
    if (c === 'fixed_delay') adv.complete_detection = { type: 'fixed_delay', wait_sec: ws }
    else if (c) adv.complete_detection = { type: c, stable_sec: ss, max_wait_sec: mw }
    if (m) adv.method = m
    if (cvOn && cv.base_url && cv.model && cv.api_key) {
      adv.copy_button_vlm = { base_url: cv.base_url, model: cv.model, api_key: cv.api_key }
    } else if (!cvOn) {
      adv.copy_button_vlm = {} // explicit removal
    }
    if (rvOn && rv.base_url && rv.model && rv.api_key) {
      adv.response_vlm = {
        base_url: rv.base_url,
        model: rv.model,
        api_key: rv.api_key,
        ...(rv.response_hint ? { response_hint: rv.response_hint } : {}),
      }
    } else if (!rvOn) {
      adv.response_vlm = {}
    }
    if (irT) adv.init_reboot = ir
    const steps = parseInitActions(iaText)
    if (steps) adv.init_action = steps
    onChange(adv)
  }

  return (
    <Collapse
      ghost
      items={[
        {
          key: 'advanced',
          label: '高级设置（可选，覆盖生成的草稿）',
          children: (
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <div>
                <Typography.Text strong>完成检测</Typography.Text>
                <div style={{ marginTop: 6 }}>
                  <Select<'' | CompletionType>
                    style={{ width: 200 }}
                    value={completion}
                    onChange={(v) => {
                      setCompletion(v)
                      buildAndEmit({ completion: v })
                    }}
                    options={[
                      { value: '', label: '默认（不覆盖）' },
                      { value: 'ui_tree_stable', label: 'ui_tree_stable' },
                      { value: 'pixel_stable', label: 'pixel_stable' },
                      { value: 'fixed_delay', label: 'fixed_delay' },
                    ]}
                  />
                  {completion === 'fixed_delay' ? (
                    <Space style={{ marginLeft: 10 }}>
                      <span>等待秒</span>
                      <InputNumber
                        min={1}
                        value={waitSec}
                        onChange={(v) => {
                          const n = v ?? 8
                          setWaitSec(n)
                          buildAndEmit({ waitSec: n })
                        }}
                      />
                    </Space>
                  ) : completion ? (
                    <Space style={{ marginLeft: 10 }}>
                      <span>stable_sec</span>
                      <InputNumber
                        min={0}
                        value={stableSec}
                        onChange={(v) => {
                          const n = v ?? 2
                          setStableSec(n)
                          buildAndEmit({ stableSec: n })
                        }}
                      />
                      <span>max_wait</span>
                      <InputNumber
                        min={1}
                        value={maxWaitSec}
                        onChange={(v) => {
                          const n = v ?? 180
                          setMaxWaitSec(n)
                          buildAndEmit({ maxWaitSec: n })
                        }}
                      />
                    </Space>
                  ) : null}
                </div>
              </div>

              <div>
                <Typography.Text strong>抽取方式 method</Typography.Text>
                <div style={{ marginTop: 6 }}>
                  <Select<'' | Method>
                    style={{ width: 200 }}
                    value={method}
                    onChange={(v) => {
                      setMethod(v)
                      buildAndEmit({ method: v })
                    }}
                    options={[
                      { value: '', label: '默认（ui_tree_only）' },
                      { value: 'ui_tree_only', label: 'ui_tree_only' },
                      { value: 'ocr_only', label: 'ocr_only' },
                      { value: 'ui_tree_then_ocr', label: 'ui_tree_then_ocr' },
                    ]}
                  />
                </div>
              </div>

              <Divider style={{ margin: '4px 0' }} />

              <VlmSection
                title="copy_button_vlm（VLM 找复制按钮）"
                on={copyVlmOn}
                onToggle={(v) => {
                  setCopyVlmOn(v)
                  buildAndEmit({ copyVlmOn: v })
                }}
                value={copyVlm}
                onChange={(v) => {
                  setCopyVlm(v)
                  buildAndEmit({ copyVlm: v, copyVlmOn: true })
                }}
              />
              <VlmSection
                title="response_vlm（VLM 看图直接抽文本）"
                on={respVlmOn}
                onToggle={(v) => {
                  setRespVlmOn(v)
                  buildAndEmit({ respVlmOn: v })
                }}
                value={respVlm}
                onChange={(v) => {
                  setRespVlm(v as typeof respVlm)
                  buildAndEmit({ respVlm: v as typeof respVlm, respVlmOn: true })
                }}
                withHint
              />

              <Divider style={{ margin: '4px 0' }} />

              <div>
                <Space>
                  <Typography.Text strong>init 前先重启设备</Typography.Text>
                  <Switch
                    checked={initReboot}
                    onChange={(v) => {
                      setInitReboot(v)
                      setInitRebootTouched(true)
                      buildAndEmit({ initReboot: v, initRebootTouched: true })
                    }}
                  />
                </Space>
              </div>
              <div>
                <Typography.Text strong>init_action（每行一个步骤,JSON）</Typography.Text>
                <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: '4px 0' }}>
                  例:{'{"action":"tap_xy","x":540,"y":1800}'} 或{' '}
                  {'{"action":"sleep","sec":1}'}。留空 = 不设置。
                </Typography.Paragraph>
                <Input.TextArea
                  rows={4}
                  value={initActionText}
                  placeholder={'{"action":"click_locator","locator":{"type":"text","value":"智能助手"}}\n{"action":"sleep","sec":1}'}
                  onChange={(e) => {
                    setInitActionText(e.target.value)
                    buildAndEmit({ initActionText: e.target.value })
                  }}
                  status={parseInitActions(initActionText) === null ? 'error' : undefined}
                />
                {parseInitActions(initActionText) === null ? (
                  <Typography.Text type="danger" style={{ fontSize: 12 }}>
                    有一行不是合法 JSON,将被忽略。
                  </Typography.Text>
                ) : null}
              </div>
            </Space>
          ),
        },
      ]}
    />
  )
}

function VlmSection({
  title,
  on,
  onToggle,
  value,
  onChange,
  withHint,
}: {
  title: string
  on: boolean
  onToggle: (v: boolean) => void
  value: VlmForm & { response_hint?: string }
  onChange: (v: VlmForm & { response_hint?: string }) => void
  withHint?: boolean
}) {
  return (
    <div>
      <Space>
        <Typography.Text strong>{title}</Typography.Text>
        <Switch checked={on} onChange={onToggle} />
      </Space>
      {on ? (
        <Space direction="vertical" size={6} style={{ width: '100%', marginTop: 8 }}>
          <Input
            placeholder="base_url"
            value={value.base_url}
            onChange={(e) => onChange({ ...value, base_url: e.target.value })}
          />
          <Input
            placeholder="model"
            value={value.model}
            onChange={(e) => onChange({ ...value, model: e.target.value })}
          />
          <Input.Password
            placeholder="api_key"
            value={value.api_key}
            onChange={(e) => onChange({ ...value, api_key: e.target.value })}
          />
          {withHint ? (
            <Input
              placeholder="response_hint（可选,定位描述）"
              value={value.response_hint ?? ''}
              onChange={(e) => onChange({ ...value, response_hint: e.target.value })}
            />
          ) : null}
        </Space>
      ) : null}
    </div>
  )
}

/**
 * Parse the init_action textarea: one JSON object per non-blank line.
 * Returns undefined when empty (=> don't set init_action), null when any
 * line is invalid JSON (=> UI shows an error, caller drops it), or the list.
 */
function parseInitActions(text: string): Array<Record<string, unknown>> | null | undefined {
  const lines = text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length === 0) return undefined
  const out: Array<Record<string, unknown>> = []
  for (const line of lines) {
    try {
      const obj = JSON.parse(line)
      if (typeof obj !== 'object' || obj === null || Array.isArray(obj) || !('action' in obj)) {
        return null
      }
      out.push(obj)
    } catch {
      return null
    }
  }
  return out
}
