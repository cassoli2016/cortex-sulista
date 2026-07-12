export interface IconButtonProps {
  /** Rótulo acessível (aria-label) — obrigatório */
  label: string;
  variant?: 'ghost' | 'outline' | 'primary';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  /** O ícone (svg Lucide) */
  children?: React.ReactNode;
  onClick?: () => void;
}
export declare function IconButton(props: IconButtonProps): JSX.Element;
