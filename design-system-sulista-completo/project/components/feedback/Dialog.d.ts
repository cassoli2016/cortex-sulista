export interface DialogProps {
  open?: boolean;
  title?: React.ReactNode;
  children?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm?: () => void;
  onCancel?: () => void;
  /** Ação destrutiva — botão vermelho */
  danger?: boolean;
  width?: number;
}
export declare function Dialog(props: DialogProps): JSX.Element;
