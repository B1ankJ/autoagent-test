import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Device } from '../types/api'
import { client } from './client'

export function useDevices() {
  return useQuery({
    queryKey: ['devices'],
    queryFn: async () => (await client.get<Device[]>('/devices')).data,
    refetchInterval: 10_000,
  })
}

export function useRefreshDevices() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => (await client.post<Device[]>('/devices/refresh')).data,
    onSuccess: (rows) => queryClient.setQueryData(['devices'], rows),
  })
}

// Backend already had /connect and /disconnect (they flip Device.enabled,
// which gates DevicePool scheduling for gui_android/agent_android) but no
// frontend ever called them — enable/disable was unreachable from the UI.
export function useConnectDevice() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (serial: string) =>
      (await client.post<Device>(`/devices/${encodeURIComponent(serial)}/connect`)).data,
    onSuccess: (row) => {
      queryClient.setQueryData<Device[]>(['devices'], (prev = []) =>
        prev.map((device) => (device.serial === row.serial ? row : device)),
      )
    },
  })
}

export function useDisconnectDevice() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (serial: string) =>
      (await client.post<Device>(`/devices/${encodeURIComponent(serial)}/disconnect`)).data,
    onSuccess: (row) => {
      queryClient.setQueryData<Device[]>(['devices'], (prev = []) =>
        prev.map((device) => (device.serial === row.serial ? row : device)),
      )
    },
  })
}

export function useDeleteDevice() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (serial: string) => {
      await client.delete(`/devices/${encodeURIComponent(serial)}`)
    },
    onSuccess: (_d, serial) => {
      queryClient.setQueryData<Device[]>(['devices'], (prev = []) =>
        prev.filter((d) => d.serial !== serial),
      )
    },
  })
}

export function useInstallAdbKeyboard() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (serial: string) =>
      (await client.post<Device>(`/devices/${serial}/install-adb-keyboard`)).data,
    onSuccess: (row) => {
      queryClient.setQueryData<Device[]>(['devices'], (prev = []) =>
        prev.map((device) => (device.serial === row.serial ? row : device)),
      )
    },
  })
}

export function useUpdateDeviceLabel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (args: { serial: string; label: string | null }) =>
      (
        await client.patch<Device>(`/devices/${args.serial}`, {
          label: args.label,
        })
      ).data,
    onSuccess: (row) => {
      queryClient.setQueryData<Device[]>(['devices'], (prev = []) =>
        prev.map((device) => (device.serial === row.serial ? row : device)),
      )
    },
  })
}

export function useEnableIme() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (serial: string) =>
      (await client.post<Device>(`/devices/${serial}/enable-ime`)).data,
    onSuccess: (row) => {
      queryClient.setQueryData<Device[]>(['devices'], (prev = []) =>
        prev.map((device) => (device.serial === row.serial ? row : device)),
      )
    },
  })
}

export function useDisableIme() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (serial: string) =>
      (await client.post<Device>(`/devices/${serial}/disable-ime`)).data,
    onSuccess: (row) => {
      queryClient.setQueryData<Device[]>(['devices'], (prev = []) =>
        prev.map((device) => (device.serial === row.serial ? row : device)),
      )
    },
  })
}

// Active Sample.session_id -> device pins (multi-turn conversations chained
// via new_session=false across separate requests — see DevicePool). Polls
// like useDevices so the remaining-TTL display stays roughly current.
export interface DeviceSession {
  session_id: string
  serial: string
  expires_in_sec: number
}

export function useDeviceSessions() {
  return useQuery({
    queryKey: ['device-sessions'],
    queryFn: async () => (await client.get<DeviceSession[]>('/devices/sessions')).data,
    refetchInterval: 10_000,
  })
}

export function useReleaseDeviceSession() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (sessionId: string) =>
      (
        await client.post<{ session_id: string; released: boolean }>(
          `/devices/sessions/${encodeURIComponent(sessionId)}/release`,
        )
      ).data,
    onSuccess: (_result, sessionId) => {
      queryClient.setQueryData<DeviceSession[]>(['device-sessions'], (prev = []) =>
        prev.filter((s) => s.session_id !== sessionId),
      )
    },
  })
}
