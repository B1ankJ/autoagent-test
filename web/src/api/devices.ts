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
