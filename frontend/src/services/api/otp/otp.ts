import {
  useMutation,
  useQuery
} from '@tanstack/react-query';
import type {
  DataTag,
  MutationFunction,
  QueryClient,
  QueryFunction,
  QueryKey,
  UseMutationOptions,
  UseMutationResult,
  UseQueryOptions,
  UseQueryResult
} from '@tanstack/react-query';

import type {
  ExtractedOtpCodeListResponse,
  ListOtpCodesApiOtpCodesGetParams,
} from '../../../types/api';

import { customInstance } from '../../client';

type SecondParameter<T extends (...args: never) => unknown> = Parameters<T>[1];

export type listOtpCodesApiOtpCodesGetResponse200 = {
  data: ExtractedOtpCodeListResponse
  status: 200
}

export type listOtpCodesApiOtpCodesGetResponseSuccess = (listOtpCodesApiOtpCodesGetResponse200) & {
  headers: Headers;
};

export type listOtpCodesApiOtpCodesGetResponse = (listOtpCodesApiOtpCodesGetResponseSuccess)

export const getListOtpCodesApiOtpCodesGetUrl = (params?: ListOtpCodesApiOtpCodesGetParams,) => {
  const normalizedParams = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined) {
      normalizedParams.append(key, value === null ? 'null' : value.toString())
    }
  });
  const stringifiedParams = normalizedParams.toString();
  return stringifiedParams.length > 0 ? `/api/otp-codes?${stringifiedParams}` : `/api/otp-codes`
}

export const listOtpCodesApiOtpCodesGet = async (params?: ListOtpCodesApiOtpCodesGetParams, options?: RequestInit): Promise<listOtpCodesApiOtpCodesGetResponse> => {
  return customInstance<listOtpCodesApiOtpCodesGetResponse>(getListOtpCodesApiOtpCodesGetUrl(params),
  { ...options, method: 'GET' }
);}

export const getListOtpCodesApiOtpCodesGetQueryKey = (params?: ListOtpCodesApiOtpCodesGetParams,) => {
  return [`/api/otp-codes`, ...(params ? [params] : [])] as const;
}

export const getListOtpCodesApiOtpCodesGetQueryOptions = <TData = Awaited<ReturnType<typeof listOtpCodesApiOtpCodesGet>>, TError = unknown>(params?: ListOtpCodesApiOtpCodesGetParams, options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof listOtpCodesApiOtpCodesGet>>, TError, TData>>, request?: SecondParameter<typeof customInstance>}
) => {
  const {query: queryOptions, request: requestOptions} = options ?? {};
  const queryKey = queryOptions?.queryKey ?? getListOtpCodesApiOtpCodesGetQueryKey(params);
  const queryFn: QueryFunction<Awaited<ReturnType<typeof listOtpCodesApiOtpCodesGet>>> = ({ signal }) => listOtpCodesApiOtpCodesGet(params, { signal, ...requestOptions });
  return { queryKey, queryFn, ...queryOptions} as UseQueryOptions<Awaited<ReturnType<typeof listOtpCodesApiOtpCodesGet>>, TError, TData> & { queryKey: DataTag<QueryKey, TData, TError> }
}

export function useListOtpCodesApiOtpCodesGet<TData = Awaited<ReturnType<typeof listOtpCodesApiOtpCodesGet>>, TError = unknown>(
  params?: ListOtpCodesApiOtpCodesGetParams, options?: { query?:Partial<UseQueryOptions<Awaited<ReturnType<typeof listOtpCodesApiOtpCodesGet>>, TError, TData>>, request?: SecondParameter<typeof customInstance>}
  , queryClient?: QueryClient
): UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> } {
  const queryOptions = getListOtpCodesApiOtpCodesGetQueryOptions(params, options)
  const query = useQuery(queryOptions, queryClient) as UseQueryResult<TData, TError> & { queryKey: DataTag<QueryKey, TData, TError> };
  return { ...query, queryKey: queryOptions.queryKey };
}

// Delete

export type deleteOtpCodeApiOtpCodesOtpIdDeleteResponse204 = {
  data: void
  status: 204
}

export type deleteOtpCodeApiOtpCodesOtpIdDeleteResponse = (deleteOtpCodeApiOtpCodesOtpIdDeleteResponse204)

export const getDeleteOtpCodeApiOtpCodesOtpIdDeleteUrl = (otpId: string,) => {
  return `/api/otp-codes/${otpId}`
}

export const deleteOtpCodeApiOtpCodesOtpIdDelete = async (otpId: string, options?: RequestInit): Promise<deleteOtpCodeApiOtpCodesOtpIdDeleteResponse> => {
  return customInstance<deleteOtpCodeApiOtpCodesOtpIdDeleteResponse>(getDeleteOtpCodeApiOtpCodesOtpIdDeleteUrl(otpId),
  { ...options, method: 'DELETE' }
);}

export const getDeleteOtpCodeApiOtpCodesOtpIdDeleteMutationOptions = <TError = unknown, TContext = unknown>(options?: { mutation?:UseMutationOptions<Awaited<ReturnType<typeof deleteOtpCodeApiOtpCodesOtpIdDelete>>, TError,{otpId: string}, TContext>, request?: SecondParameter<typeof customInstance>}
): UseMutationOptions<Awaited<ReturnType<typeof deleteOtpCodeApiOtpCodesOtpIdDelete>>, TError,{otpId: string}, TContext> => {
  const mutationKey = ['deleteOtpCodeApiOtpCodesOtpIdDelete'];
  const {mutation: mutationOptions, request: requestOptions} = options ?
    options.mutation && 'mutationKey' in options.mutation && options.mutation.mutationKey ?
    options
    : {...options, mutation: {...options.mutation, mutationKey}}
    : {mutation: { mutationKey }, request: undefined};
  const mutationFn: MutationFunction<Awaited<ReturnType<typeof deleteOtpCodeApiOtpCodesOtpIdDelete>>, {otpId: string}> = (props) => {
    const {otpId} = props ?? {};
    return deleteOtpCodeApiOtpCodesOtpIdDelete(otpId, requestOptions)
  }
  return { mutationFn, ...mutationOptions }
}

export const useDeleteOtpCodeApiOtpCodesOtpIdDelete = <TError = unknown, TContext = unknown>(options?: { mutation?:UseMutationOptions<Awaited<ReturnType<typeof deleteOtpCodeApiOtpCodesOtpIdDelete>>, TError,{otpId: string}, TContext>, request?: SecondParameter<typeof customInstance>}
  , queryClient?: QueryClient): UseMutationResult<Awaited<ReturnType<typeof deleteOtpCodeApiOtpCodesOtpIdDelete>>, TError, {otpId: string}, TContext> => {
  return useMutation(getDeleteOtpCodeApiOtpCodesOtpIdDeleteMutationOptions(options), queryClient);
}
