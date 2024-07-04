import asyncio
import py_nillion_client as nillion
import os

from py_nillion_client import NodeKey, UserKey
from dotenv import load_dotenv
from nillion_python_helpers import get_quote_and_pay, create_nillion_client, create_payments_config

from cosmpy.aerial.client import LedgerClient
from cosmpy.aerial.wallet import LocalWallet
from cosmpy.crypto.keypairs import PrivateKey

home = os.getenv("HOME")
load_dotenv(f"{home}/.config/nillion/nillion-devnet.env")

# Hypothetical TelemetryClient class
class TelemetryClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def send_telemetry_event(self, event_name, properties=None):
        # Simulate sending telemetry data to a telemetry service
        print(f"Sending telemetry event '{event_name}' with properties: {properties}")

# Initialize telemetry client
telemetry_client = TelemetryClient(api_key="your_telemetry_api_key")

async def main():
    # 1. Initial setup
    # 1.1. Get cluster_id, grpc_endpoint, & chain_id from the .env file
    cluster_id = os.getenv("NILLION_CLUSTER_ID")
    grpc_endpoint = os.getenv("NILLION_NILCHAIN_GRPC")
    chain_id = os.getenv("NILLION_NILCHAIN_CHAIN_ID")
    # 1.2 pick a seed and generate user and node keys
    seed = "my_seed"
    userkey = UserKey.from_seed(seed)
    nodekey = NodeKey.from_seed(seed)

    # 2. Initialize NillionClient against nillion-devnet
    # Create Nillion Client for user
    client = create_nillion_client(userkey, nodekey)

    party_id = client.party_id
    user_id = client.user_id

    # Send telemetry event: Initial setup
    telemetry_client.send_telemetry_event("InitialSetup", {"cluster_id": cluster_id, "user_id": user_id})

    # 3. Pay for and store the program
    # Set the program name and path to the compiled program
    program_name = "my_telemetry_program"
    program_mir_path = f"../nada_quickstart_programs/target/{program_name}.nada.bin"

    # Create payments config, client and wallet
    payments_config = create_payments_config(chain_id, grpc_endpoint)
    payments_client = LedgerClient(payments_config)
    payments_wallet = LocalWallet(
        PrivateKey(bytes.fromhex(os.getenv("NILLION_NILCHAIN_PRIVATE_KEY_0"))),
        prefix="nillion",
    )

    # Pay to store the program and obtain a receipt of the payment
    receipt_store_program = await get_quote_and_pay(
        client,
        nillion.Operation.store_program(program_mir_path),
        payments_wallet,
        payments_client,
        cluster_id,
    )

    # Store the program
    action_id = await client.store_program(
        cluster_id, program_name, program_mir_path, receipt_store_program
    )

    # Send telemetry event: Program stored
    telemetry_client.send_telemetry_event("ProgramStored", {"program_name": program_name, "action_id": action_id})

    # Create a variable for the program_id, which is the {user_id}/{program_name}. We will need this later
    program_id = f"{user_id}/{program_name}"
    print("Stored program. action_id:", action_id)
    print("Stored program_id:", program_id)

    # 4. Create a secret, add permissions, pay for and store it in the network
    new_secret = nillion.NadaValues(
        {
            "secret_value": nillion.SecretInteger(42),
        }
    )

    # Set permissions for the client to compute on the program
    permissions = nillion.Permissions.default_for_user(client.user_id)
    permissions.add_compute_permissions({client.user_id: {program_id}})

    # Pay for and store the secret in the network and print the returned store_id
    receipt_store = await get_quote_and_pay(
        client,
        nillion.Operation.store_values(new_secret, ttl_days=5),
        payments_wallet,
        payments_client,
        cluster_id,
    )
    # Store a secret
    store_id = await client.store_values(
        cluster_id, new_secret, permissions, receipt_store
    )
    print(f"Computing using program {program_id}")
    print(f"Use secret store_id: {store_id}")

    # Send telemetry event: Secret stored
    telemetry_client.send_telemetry_event("SecretStored", {"store_id": store_id})

    # 5. Perform computation using the stored program and secret
    compute_bindings = nillion.ProgramBindings(program_id)
    compute_bindings.add_input_party("Party1", party_id)
    compute_bindings.add_output_party("Party1", party_id)

    # Add a computation time secret for the operation
    computation_time_secrets = nillion.NadaValues({"operation_time": nillion.SecretInteger(10)})

    # Pay for the compute
    receipt_compute = await get_quote_and_pay(
        client,
        nillion.Operation.compute(program_id, computation_time_secrets),
        payments_wallet,
        payments_client,
        cluster_id,
    )

    # Compute on the secret
    compute_id = await client.compute(
        cluster_id,
        compute_bindings,
        [store_id],
        computation_time_secrets,
        receipt_compute,
    )

    # Send telemetry event: Computation started
    telemetry_client.send_telemetry_event("ComputationStarted", {"compute_id": compute_id})

    # Wait for compute to complete and return the result
    print(f"Computation started. compute_id: {compute_id}")
    while True:
        compute_event = await client.next_compute_event()
        if isinstance(compute_event, nillion.ComputeFinishedEvent):
            print(f"✅  Compute complete for compute_id {compute_event.uuid}")
            print(f"🖥️  The result is {compute_event.result.value}")
            telemetry_client.send_telemetry_event("ComputationComplete", {"compute_id": compute_event.uuid})
            return compute_event.result.value

