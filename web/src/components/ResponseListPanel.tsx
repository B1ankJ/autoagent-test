import { PlusOutlined } from '@ant-design/icons'
import { App, Button, Empty, Form, Input, List, Modal, Select, Space } from 'antd'
import { useMemo, useState } from 'react'

interface ResponseListEntry {
  target_profile: string
  response: string
  response_excerpt: string
  added_at: string
}

interface ResponseListPanelProps {
  entries: ResponseListEntry[] | undefined
  addPending: boolean
  removePending: boolean
  onAdd: (values: { target_profile: string; response: string }) => Promise<void>
  onRemove: (entry: { target_profile: string; response: string }) => Promise<void>
  emptyText: string
  addButtonLabel: string
  addModalTitle: string
}

/** Shared list UI for the DingTalk rule-2 whitelist/blacklist — same shape
 * (profile-scoped response entries), same profile filter + pagination +
 * manual add/remove, differing only in labels/copy between the two. */
export function ResponseListPanel({
  entries,
  addPending,
  removePending,
  onAdd,
  onRemove,
  emptyText,
  addButtonLabel,
  addModalTitle,
}: ResponseListPanelProps) {
  const { message } = App.useApp()
  const [profileFilter, setProfileFilter] = useState<string | undefined>(undefined)
  const [addOpen, setAddOpen] = useState(false)
  const [form] = Form.useForm<{ target_profile: string; response: string }>()

  const profiles = useMemo(
    () => Array.from(new Set((entries ?? []).map((e) => e.target_profile))).sort(),
    [entries],
  )
  const filtered = useMemo(
    () =>
      profileFilter
        ? (entries ?? []).filter((e) => e.target_profile === profileFilter)
        : (entries ?? []),
    [entries, profileFilter],
  )

  const handleAdd = async () => {
    try {
      const values = await form.validateFields()
      await onAdd(values)
      message.success('已新增')
      setAddOpen(false)
      form.resetFields()
    } catch (e) {
      if (e instanceof Error) message.error(e.message)
    }
  }

  return (
    <>
      <Space size={8} style={{ marginBottom: 12 }}>
        <Select
          allowClear
          placeholder="按 Profile 筛选"
          style={{ width: 200 }}
          value={profileFilter}
          onChange={setProfileFilter}
          options={profiles.map((p) => ({ value: p, label: p }))}
        />
        <Button icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
          {addButtonLabel}
        </Button>
      </Space>
      <List
        dataSource={filtered}
        pagination={{ pageSize: 8, hideOnSinglePage: true, size: 'small' }}
        locale={{
          emptyText: <Empty description={profileFilter ? '该 Profile 下没有记录' : emptyText} />,
        }}
        renderItem={(entry, idx) => (
          <List.Item
            key={`${entry.target_profile}-${idx}`}
            actions={[
              <Button
                key="remove"
                size="small"
                danger
                loading={removePending}
                onClick={() =>
                  onRemove({
                    target_profile: entry.target_profile,
                    response: entry.response,
                  }).catch((e) => message.error((e as Error).message))
                }
              >
                删除
              </Button>,
            ]}
          >
            <List.Item.Meta
              title={<span className="aa-mono">{entry.target_profile}</span>}
              description={
                <>
                  <div>{entry.response_excerpt || '(空)'}</div>
                  <div className="aa-muted" style={{ fontSize: 11, marginTop: 2 }}>
                    {new Date(entry.added_at).toLocaleString()}
                  </div>
                </>
              }
            />
          </List.Item>
        )}
      />
      <Modal
        open={addOpen}
        title={addModalTitle}
        onCancel={() => setAddOpen(false)}
        onOk={handleAdd}
        confirmLoading={addPending}
        okText="新增"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="target_profile"
            label="Profile"
            rules={[{ required: true, message: '请输入 profile 名称' }]}
          >
            <Input placeholder="target_profile" />
          </Form.Item>
          <Form.Item
            name="response"
            label="响应内容(需完全匹配)"
            rules={[{ required: true, message: '请输入响应文本' }]}
          >
            <Input.TextArea rows={4} placeholder="需要与实际响应完全一致(去除首尾空白后)" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
