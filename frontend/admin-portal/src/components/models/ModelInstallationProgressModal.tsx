import React from 'react';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

interface ProgressData {
  job_id: string;
  model_id: string;
  provider_type: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress_pct: number;
  current_step?: string;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

interface ModelInstallationProgressModalProps {
  jobId: string;
  modelId: string;
  onClose: () => void;
}

// Create local axios instance
const apiClient = axios.create({
  baseURL: 'http://localhost:3000',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add request interceptor for auth token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

const ModelInstallationProgressModal: React.FC<ModelInstallationProgressModalProps> = ({
  jobId,
  modelId,
  onClose,
}) => {
  const { data, isLoading, error } = useQuery<ProgressData>({
    queryKey: ['installationProgress', jobId],
    queryFn: async () => {
      const response = await apiClient.get<ProgressData>(
        `/api/v1/models/install/jobs/${jobId}`
      );
      return response.data;
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2000;
      // Stop polling when job completes or fails
      if (data.status === 'completed' || data.status === 'failed') {
        return false;
      }
      return 2000; // Poll every 2 seconds
    },
    retry: 3,
  });

  const getStatusColor = (status: string | undefined) => {
    switch (status) {
      case 'completed':
        return 'text-green-600';
      case 'failed':
        return 'text-red-600';
      case 'running':
        return 'text-blue-600';
      case 'pending':
        return 'text-yellow-600';
      default:
        return 'text-gray-600';
    }
  };

  const getProgressBarColor = (status: string | undefined) => {
    switch (status) {
      case 'completed':
        return 'bg-green-500';
      case 'failed':
        return 'bg-red-500';
      case 'running':
        return 'bg-blue-500';
      case 'pending':
        return 'bg-yellow-500';
      default:
        return 'bg-gray-500';
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full">
        <h2 className="text-xl font-semibold mb-4">
          Installing {modelId}
        </h2>

        {isLoading && (
          <div className="text-center py-4">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-2 text-gray-600">Loading progress...</p>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded p-4 mb-4">
            <p className="text-red-800 font-medium">Error loading progress</p>
            <p className="text-red-600 text-sm mt-1">{String(error)}</p>
          </div>
        )}

        {data && (
          <>
            <div className="mb-4">
              <div className="flex justify-between items-center mb-2">
                <span className={`font-medium ${getStatusColor(data.status)}`}>
                  Status: {data.status.toUpperCase()}
                </span>
                <span className="text-gray-600">
                  {Math.round(data.progress_pct)}%
                </span>
              </div>

              <div className="w-full bg-gray-200 rounded-full h-3">
                <div
                  className={`${getProgressBarColor(data.status)} h-3 rounded-full transition-all duration-300`}
                  style={{ width: `${data.progress_pct}%` }}
                />
              </div>
            </div>

            {data.current_step && (
              <div className="mb-4">
                <p className="text-sm text-gray-700">
                  <span className="font-medium">Current step:</span>{' '}
                  {data.current_step}
                </p>
              </div>
            )}

            {data.error_message && (
              <div className="bg-red-50 border border-red-200 rounded p-4 mb-4">
                <p className="text-red-800 font-medium">Installation Failed</p>
                <p className="text-red-600 text-sm mt-1">{data.error_message}</p>
              </div>
            )}

            {data.status === 'completed' && (
              <div className="bg-green-50 border border-green-200 rounded p-4 mb-4">
                <p className="text-green-800 font-medium">
                  ✓ Installation completed successfully!
                </p>
              </div>
            )}

            <div className="mt-4 text-xs text-gray-500">
              <p>Job ID: {data.job_id}</p>
              {data.started_at && (
                <p>Started: {new Date(data.started_at).toLocaleString()}</p>
              )}
              {data.completed_at && (
                <p>Completed: {new Date(data.completed_at).toLocaleString()}</p>
              )}
            </div>
          </>
        )}

        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            disabled={data?.status === 'running' || data?.status === 'pending'}
            className={`px-4 py-2 rounded font-medium ${
              data?.status === 'running' || data?.status === 'pending'
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            }`}
          >
            {data?.status === 'running' || data?.status === 'pending'
              ? 'Installing...'
              : 'Close'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ModelInstallationProgressModal;
