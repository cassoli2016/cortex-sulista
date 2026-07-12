export interface TagProps {
  /** Tinge de laranja */
  accent?: boolean;
  /** Mostra o × de remover */
  onRemove?: () => void;
  children?: React.ReactNode;
}
export declare function Tag(props: TagProps): JSX.Element;
