export interface ToastProps {
  tone?: 'success' | 'warning' | 'danger' | 'info';
  title?: React.ReactNode;
  children?: React.ReactNode;
  onClose?: () => void;
}
export declare function Toast(props: ToastProps): JSX.Element;
