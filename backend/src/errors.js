/** An error that maps directly to an HTTP response `{ error: code, detail }`. */
export class HttpError extends Error {
  constructor(status, code, detail) {
    super(detail);
    this.name = 'HttpError';
    this.status = status;
    this.code = code;
  }
}

export const invalidFile = (detail) => new HttpError(400, 'invalid_file', detail);
export const badRequest = (detail) => new HttpError(400, 'bad_request', detail);
export const unauthorized = () => new HttpError(401, 'unauthorized', 'missing or wrong X-Api-Key');
export const tooLarge = (limitMb) => new HttpError(413, 'too_large', `request body exceeds ${limitMb} MB`);
