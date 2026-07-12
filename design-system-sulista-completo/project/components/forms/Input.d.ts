export interface InputProps {
  label?: string;
  hint?: string;
  /** Mensagem de erro; muda a borda para vermelho */
  error?: string;
  /** Prefixo textual (ex.: "R$") */
  prefix?: string;
  /** Fonte mono para códigos (placa, CT-e) */
  mono?: boolean;
  placeholder?: string;
  value?: string;
  onChange?: (e: any) => void;
  disabled?: boolean;
  type?: string;
}
export declare function Input(props: InputProps): JSX.Element;
