import { useMutation } from '@tanstack/react-query'
import { LoginRequest, LoginResponse } from '../types/api'
import { client } from './client'

export function useLogin() {
  return useMutation({
    mutationFn: async (body: LoginRequest) => {
      const response = await client.post<LoginResponse>('/auth/login', body)
      return response.data
    },
  })
}

export async function logoutApi() {
  try {
    await client.post('/auth/logout')
  } catch {
    // Best effort logout: token cleanup still happens client-side.
  }
}
