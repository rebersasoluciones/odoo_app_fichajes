import { rpc } from "@web/core/network/rpc";

export class QuicklinkApi {
    constructor(token) {
        this.base = `/fichaje/${encodeURIComponent(token)}/api`;
    }

    async call(route, params = {}) {
        let response;
        try {
            response = await rpc(`${this.base}/${route}`, params, { silent: true });
        } catch (error) {
            const wrapped = new Error(
                error && error.name === "RPC_ERROR"
                    ? "No se ha podido completar. Inténtalo de nuevo en un momento."
                    : "Sin conexión. Comprueba la cobertura e inténtalo otra vez."
            );
            wrapped.cause = error;
            throw wrapped;
        }
        if (response && response.error) {
            const error = new Error(response.error);
            error.invalidToken = Boolean(response.invalid_token);
            throw error;
        }
        return response ? response.result : null;
    }
}
