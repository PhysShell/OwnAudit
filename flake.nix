{
  description = "OwnAudit development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    mcp-servers-nix = {
      url = "github:PhysShell/mcp-servers-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      nixpkgs,
      mcp-servers-nix,
      ...
    }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };

      python-env = pkgs.python3.withPackages (
        ps: with ps; [
          pip
          requests
          boto3
          psycopg2
          python-dateutil
          debugpy
          ipython
          tqdm
        ]
      );

      codex-project-config = mcp-servers-nix.lib.mkConfig pkgs {
        flavor = "codex";
        format = "toml";
        fileName = "config.toml";

        settings.servers.context7 = {
          url = "https://mcp.context7.com/mcp;
          startup_timeout_sec = 40;
          tool_timeout_sec = 60;
        };
      };

      sync-codex-config = pkgs.writeShellApplication {
        name = "sync-codex-config";
        runtimeInputs = [ pkgs.coreutils ];
        text = ''
          mkdir -p .codex
          install -m 0644 ${codex-project-config} .codex/config.toml
          echo "Wrote .codex/config.toml"
        '';
      };
    in
    {
      packages.${system} = {
        codex-project-config = codex-project-config;
        sync-codex-config = sync-codex-config;
      };

      apps.${system}.sync-codex-config = {
        type = "app";
        program = "${sync-codex-config}/bin/sync-codex-config";
        meta.description = "Write generated Codex MCP config to .codex/config.toml";
      };

      checks.${system}.codex-project-config = codex-project-config;

      devShells.${system}.default = pkgs.mkShellNoCC {
        packages = [
          python-env
        ];
      };
    };
}
